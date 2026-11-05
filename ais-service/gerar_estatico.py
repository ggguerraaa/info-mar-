"""
Rodada do GitHub Actions: o Info-Maré sem servidor.

O GitHub liga uma máquina a cada ~30 min e roda este script, que:
  1. abre o banco (restaurado da rodada anterior pelo workflow);
  2. escuta o AISstream por ESCUTA_SEGUNDOS (mesmo coletor do backend);
  3. roda os jobs: praticagem, índice operacional + alertas, limpeza;
  4. grava em painel/out/dados/ os mesmos JSON que a API servia
     (o painel lê esses arquivos em vez de chamar /api);
  5. compara o schedule (schedule/schedule.csv) com o real.

Este é o ÚNICO coletor: o AISstream aceita uma conexão por chave. Não rode o
backend (backend_app.py) com a mesma chave ao mesmo tempo.

Uso local:
    python gerar_estatico.py                 # escuta 480 s
    ESCUTA_SEGUNDOS=0 python gerar_estatico.py   # só gera os arquivos
"""

from __future__ import annotations

import asyncio
import json
import os
import pathlib
import sys
import time
from datetime import datetime, timezone

import ais_stream
import backend_app as api
import sea_conditions
from painel_porto import todos_os_slugs
from referencias_ais import bandeira_por_mmsi, nome_tipo
from scheduler import job_atualizar_praticagem, job_monitorar_saude_do_sistema, job_recalcular_indice_operacional
from storage import apagar_posicoes_antigas, conexao, inicializar_banco

RAIZ = pathlib.Path(__file__).resolve().parent.parent
SAIDA = pathlib.Path(os.getenv("SAIDA_DADOS") or RAIZ / "painel" / "out" / "dados")
ESCUTA_SEGUNDOS = int(os.getenv("ESCUTA_SEGUNDOS", "480"))
RETENCAO_DIAS = int(os.getenv("RETENCAO_DIAS", "7"))
RASTRO_HORAS = 24
PARALELO = int(os.getenv("OPEN_METEO_PARALELO", "8"))

# Open-Meteo a partir das máquinas do GitHub: às vezes não responde. Sem isto,
# cada chamada que falha espera 2 × 15 s, e a mesma consulta falha de novo no
# índice, no painel e no resumo. Aqui: espera menor e, se uma consulta falhou
# nesta rodada, as repetições dela falham na hora (o bloco fica "sem dado").
sea_conditions.TIMEOUT_S = int(os.getenv("OPEN_METEO_TIMEOUT_S", "8"))
_get_json_original = sea_conditions._get_json
_falhas: set = set()


def _get_json_rodada(url: str, params: dict) -> dict:
    chave = (url, tuple(sorted(params.items())))
    if chave in _falhas:
        raise RuntimeError("sem resposta nesta rodada (já tentado)")
    try:
        return _get_json_original(url, params)
    except Exception:
        _falhas.add(chave)
        raise


sea_conditions._get_json = _get_json_rodada


def log(msg: str) -> None:
    print(f"[{datetime.now(timezone.utc):%H:%M:%S}] {msg}", flush=True)


def gravar(caminho: str, dados) -> None:
    arquivo = SAIDA / caminho
    arquivo.parent.mkdir(parents=True, exist_ok=True)
    arquivo.write_text(json.dumps(dados, ensure_ascii=False, separators=(",", ":"), default=str), encoding="utf-8")


def tentar(nome: str, funcao):
    """Uma fonte fora do ar não derruba a rodada: o arquivo daquela parte só
    não é atualizado (o painel mostra a hora em que foi gerado)."""
    inicio = time.monotonic()
    try:
        resultado = funcao()
        log(f"{nome}: ok ({time.monotonic() - inicio:.1f}s)")
        return resultado
    except Exception as erro:  # noqa: BLE001
        log(f"{nome}: FALHOU — {erro}")
        return None


# ---------------------------------------------------------------- 1. AIS

async def coletar_ais() -> None:
    if not ais_stream.AISSTREAM_API_KEY:
        log("AISSTREAM_API_KEY vazia: sem coleta nesta rodada (usa as posições do banco).")
        ais_stream.carregar_ultimas_posicoes_do_banco()
        return
    if ESCUTA_SEGUNDOS <= 0:
        ais_stream.carregar_ultimas_posicoes_do_banco()
        return
    log(f"Escutando o AISstream por {ESCUTA_SEGUNDOS}s...")
    tarefas = [asyncio.create_task(ais_stream.escutar_ais_stream()),
               asyncio.create_task(ais_stream.tarefa_de_manutencao())]
    await asyncio.sleep(ESCUTA_SEGUNDOS)
    for t in tarefas:
        t.cancel()
    await asyncio.gather(*tarefas, return_exceptions=True)  # grava o último lote e fecha o WebSocket
    log(f"AIS: {len(ais_stream.ultimas_posicoes)} navios com posição nas últimas {ais_stream.MEMORIA_HORAS} h.")


# ---------------------------------------------------------------- 4. arquivos

def exportar_navios() -> None:
    gravar("navios.json", api.navios_no_mapa())

    # Todos os navios conhecidos: busca e "Meus navios" filtram no navegador.
    with conexao() as conn:
        infos = {r[0]: r for r in conn.execute(
            "SELECT mmsi, nome_navio, imo, tipo_codigo, destino FROM navios_info")}
        ultimas = {r[0]: r for r in conn.execute(
            """SELECT p.mmsi, p.latitude, p.longitude, p.velocidade_nos, p.status_navegacao, p.timestamp_utc
               FROM posicoes_navio p JOIN (SELECT mmsi, MAX(timestamp_utc) t FROM posicoes_navio GROUP BY mmsi) u
               ON p.mmsi = u.mmsi AND p.timestamp_utc = u.t""")}
    agora = datetime.now(timezone.utc)
    linhas = []
    for mmsi in sorted(set(infos) | set(ultimas)):
        i, p = infos.get(mmsi), ultimas.get(mmsi)
        memoria = ais_stream.ultimas_posicoes.get(mmsi)
        linhas.append([
            mmsi,
            (i[1] if i else None) or (memoria or {}).get("nome_navio"),
            i[2] if i else None,
            nome_tipo(i[3]) if i else None,
            bandeira_por_mmsi(mmsi),
            i[4] if i else None,
            p[4] if p else None, p[3] if p else None, p[1] if p else None, p[2] if p else None,
            int((agora - datetime.fromisoformat(p[5])).total_seconds()) if p else None,
            memoria is not None,
        ])
    gravar("navios/todos.json", {
        "campos": ["mmsi", "nome", "imo", "tipo", "bandeira", "destino_informado", "status_codigo",
                   "velocidade_nos", "latitude", "longitude", "idade_s", "tem_posicao"],
        "navios": linhas,
        "gerado_em": agora.isoformat(),
    })

    # Card e rastro de cada navio com posição na retenção
    cards = 0
    gerado = {"gerado_em": agora.isoformat()}  # o painel soma o tempo passado ao idade_s
    for mmsi in ultimas:
        try:
            gravar(f"navios/{mmsi}.json", {**api.card_navio(mmsi), **gerado})
            gravar(f"navios/{mmsi}/trajetoria.json", {**api.trajetoria_navio(mmsi, horas=RASTRO_HORAS), **gerado})
            cards += 1
        except Exception as erro:  # noqa: BLE001
            log(f"card {mmsi}: {erro}")
    log(f"Navios: {len(linhas)} conhecidos, {cards} cards/rastros.")


def aquecer_open_meteo() -> None:
    """Consulta o tempo de todos os portos em paralelo antes do índice e dos
    painéis: depois disso, índice, painel e resumo leem do cache (10 min)."""
    from concurrent.futures import ThreadPoolExecutor
    from config.port_operations_config import PORT_CONFIGS
    from painel_porto import MANAUS
    from sea_conditions import buscar_condicoes_operacionais, buscar_tempo_porto

    coords = [(c.lat, c.lon) for c in PORT_CONFIGS.values()]
    tarefas = [lambda la=la, lo=lo: buscar_condicoes_operacionais(la, lo) for la, lo in coords]
    tarefas += [lambda la=la, lo=lo: buscar_tempo_porto(la, lo) for la, lo in [*coords, (MANAUS["lat"], MANAUS["lon"])]]
    with ThreadPoolExecutor(max_workers=PARALELO) as ex:
        list(ex.map(lambda f: tentar_quieto(f), tarefas))
    log(f"Open-Meteo: {len(_falhas)} consulta(s) sem resposta nesta rodada.")


def tentar_quieto(funcao):
    try:
        return funcao()
    except Exception:  # noqa: BLE001
        return None


def exportar_portos() -> None:
    from concurrent.futures import ThreadPoolExecutor

    gravar("portos.json", api.listar_portos())
    gravar("portos/resumo.json", api.resumo(""))
    with ThreadPoolExecutor(max_workers=PARALELO) as ex:
        paineis = dict(zip(todos_os_slugs(), ex.map(lambda s: tentar_quieto(lambda: api.painel_do_porto(s)), todos_os_slugs())))
    for slug, dados in paineis.items():
        if dados:
            gravar(f"portos/{slug}/painel.json", dados)
    log(f"Painéis: {sum(1 for d in paineis.values() if d)} de {len(paineis)} portos.")


_frota: dict = {}


def preparar_frota() -> None:
    """MMSI pelo IMO e armador (com fonte) no cadastro, antes dos cards."""
    import frota
    cfg = frota.carregar()
    _frota.update(cfg=cfg, navios=frota.aplicar_armadores(cfg))
    achados = sum(1 for n in _frota["navios"].values() if n["mmsi"])
    log(f"Frota: {achados} de {len(_frota['navios'])} navios com MMSI conhecido.")


def exportar_frota() -> None:
    import frota
    if not _frota:
        preparar_frota()
    dados = frota.exportar_frota(_frota["cfg"], _frota["navios"])
    gravar("frota.json", dados)
    com_posicao = sum(1 for n in dados["navios"] if n["posicao"])
    log(f"Frota: {com_posicao} navios com posição nos últimos {dados['retencao_dias']} dias.")
    mmsis = {n["mmsi"] for n in _frota["navios"].values() if n["mmsi"]}
    gravar("rastros.json", frota.exportar_rastros(mmsis))


def exportar_schedule() -> None:
    from schedule_status import gerar_status
    dados = gerar_status()
    # armador de cada navio do schedule, pelo IMO da frota (filtro na tela)
    por_imo = {n["imo"]: n["armador"] for n in _frota.get("navios", {}).values()}
    for n in dados["navios"]:
        n["armador"] = por_imo.get(n["imo"])
    gravar("schedule.json", dados)


# ---------------------------------------------------------------- principal

def main() -> int:
    inicio = datetime.now(timezone.utc)
    inicializar_banco()

    asyncio.run(coletar_ais())

    tentar("praticagem", job_atualizar_praticagem)
    tentar("Open-Meteo (todos os portos)", aquecer_open_meteo)
    tentar("índice operacional e alertas", job_recalcular_indice_operacional)
    tentar("saúde do sistema", job_monitorar_saude_do_sistema)
    tentar("limpeza", lambda: apagar_posicoes_antigas(dias=RETENCAO_DIAS))

    tentar("frota (MMSI e armador)", preparar_frota)
    tentar("navios", exportar_navios)
    tentar("frota", exportar_frota)
    tentar("portos", exportar_portos)
    tentar("schedule", exportar_schedule)

    gravar("meta.json", {
        "gerado_em": datetime.now(timezone.utc).isoformat(),
        "rodada_iniciada_em": inicio.isoformat(),
        "escuta_s": ESCUTA_SEGUNDOS if ais_stream.AISSTREAM_API_KEY else 0,
        "intervalo_min": int(os.getenv("INTERVALO_MIN", "30")),
        "navios_em_memoria": len(ais_stream.ultimas_posicoes),
    })
    with conexao() as conn:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")  # banco num arquivo só, para guardar
        conn.execute("VACUUM")
    log(f"Pronto em {(datetime.now(timezone.utc) - inicio).total_seconds():.0f}s → {SAIDA}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
