"""
Coletor AIS (AISstream.io, WebSocket), tarefa de fundo do backend no mesmo
event loop. Todos os navios da caixa, sem filtro de navio nem frota.

Medido contra o serviço real (tools/verificar_ais.py, 02/11/2026, 10 min,
caixa lat -56..6 / lon -73..-25, sem filtro de tipo):
  PositionReport (Classe A)       0,48 msg/s  158 navios  com posição
  ShipStaticData                  0,12 msg/s   65 navios  (59 com IMO)
  StandardClassBPositionReport    0,05 msg/s   22 navios  com posição
  StaticDataReport (Classe B)     0,04 msg/s   18 navios  (nome/tipo/dimensões)
  Total ~0,7 msg/s, 180 navios com posição. Classe B soma 22 navios que só
  com PositionReport ficavam de fora. ExtendedClassBPositionReport não
  apareceu na amostra, mas traz posição e nome: assinado também.

Cobertura é só de antenas terrestres: longe da costa pode não haver posição.

Memória e disco (instância gratuita do Render, ~512 MB):
  - última posição de cada navio fica em memória (ultimas_posicoes); o mapa
    lê dali. Navio sem posição há mais de 6 h sai da memória (fica no banco).
  - no banco, no máximo 1 posição por navio por minuto, gravada em lote a
    cada ~10 s; só os campos usados (não a mensagem inteira).
  - a taxa de mensagens, navios em memória e uso de memória vão para o log a
    cada 10 min (MEDICAO_INTERVALO_S) e para /api/sistema/saude.

O AISstream aceita um coletor por chave: outra conexão com a mesma chave é
recusada (429). Ao desligar, a tarefa é cancelada e o WebSocket fechado; ao
reconectar, a espera cresce (5 s, 10 s, 20 s... até 5 min), e começa em 1 min
quando o motivo é 429 (a instância antiga ainda está saindo, ex.: deploy).
"""

import asyncio
import json
import logging
import os
import time
from collections import Counter
from datetime import datetime, timedelta, timezone

import websockets
from dotenv import load_dotenv

from storage import (
    abrir_periodo_coleta,
    contar_registros,
    fechar_periodo_coleta,
    gravar_infos,
    gravar_posicoes,
    obter_posicoes_recentes,
    registrar_sinal_coleta,
)

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("ais-stream")

AISSTREAM_API_KEY = os.getenv("AISSTREAM_API_KEY", "")
AISSTREAM_URL = "wss://stream.aisstream.io/v0/stream"

# Lista de caixas [[lat_min, lon_min], [lat_max, lon_max]] em JSON. Padrão:
# costa do Brasil, Argentina, Uruguai e hidrovia Paraguai-Paraná.
CAIXAS_PADRAO = [[[-56.0, -73.0], [6.0, -25.0]]]
AIS_CAIXAS = json.loads(os.getenv("AIS_CAIXAS", "") or "null") or CAIXAS_PADRAO

TIPOS_POSICAO = ("PositionReport", "StandardClassBPositionReport", "ExtendedClassBPositionReport")
TIPOS_ESTATICOS = ("ShipStaticData", "StaticDataReport")

INTERVALO_GRAVACAO_S = int(os.getenv("AIS_INTERVALO_GRAVACAO_S", "60"))  # por navio
INTERVALO_LOTE_S = 10        # de quanto em quanto tempo o lote vai para o banco
INTERVALO_SINAL_S = 60       # atualização do período de coleta
MEMORIA_HORAS = 6            # navio sem posição há mais que isso sai da memória
MEDICAO_INTERVALO_S = 600

# Última posição de cada navio, em memória (servida pelo /api/navios).
ultimas_posicoes: dict[str, dict] = {}
_ultima_gravacao: dict[str, float] = {}
_nomes_gravados: dict[str, str] = {}  # evita regravar o nome a cada posição
_lote_posicoes: list[dict] = []
_lote_infos: list[dict] = []

# Medição (log + /api/sistema/saude)
_contagem_tipos: Counter = Counter()
_inicio_medicao = time.monotonic()
medicao: dict = {}
conectado = False


def _agora() -> datetime:
    return datetime.now(timezone.utc)


def _limpar_texto(texto: str | None) -> str | None:
    """Nomes/destinos do AIS vêm preenchidos com espaços e '@'."""
    if not texto:
        return None
    limpo = texto.replace("@", " ").strip()
    return limpo or None


def _normalizar_time_utc(bruto: str | None) -> str:
    """AISstream manda "2026-10-16 12:34:56.123456789 +0000 UTC" — formato que
    o datetime() do SQLite não entende. Grava sempre em ISO UTC."""
    if bruto:
        try:
            return datetime.fromisoformat(bruto[:19]).replace(tzinfo=timezone.utc).isoformat()
        except ValueError:
            pass
    return _agora().isoformat()


def _ou_none(valor, sem_dado):
    """Valores reservados do AIS que significam 'não disponível'."""
    if valor is None:
        return None
    return None if valor >= sem_dado else valor


def _dimensoes(dim: dict | None) -> tuple[float | None, float | None]:
    dim = dim or {}
    a, b, c, d = (dim.get(k) or 0 for k in "ABCD")
    return (a + b) or None, (c + d) or None


def carregar_ultimas_posicoes_do_banco() -> None:
    """Reabastece a memória quando o backend sobe (reinício no Render) —
    sem isso o mapa fica vazio até cada navio transmitir de novo."""
    for p in obter_posicoes_recentes(horas=MEMORIA_HORAS):
        p.pop("id", None)
        ultimas_posicoes[p["mmsi"]] = p
        if p.get("nome_navio"):
            _nomes_gravados[p["mmsi"]] = p["nome_navio"]
    logger.info("Memória AIS reabastecida do banco: %d navios das últimas %d h", len(ultimas_posicoes), MEMORIA_HORAS)


def _handle_message(raw: str | bytes) -> None:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        logger.error("Mensagem não é JSON válido: %r", raw[:200])
        return

    tipo = data.get("MessageType")
    _contagem_tipos[tipo] += 1
    if tipo in TIPOS_POSICAO:
        _handle_posicao(data, tipo)
    elif tipo == "ShipStaticData":
        _handle_ship_static_data(data)
    elif tipo == "StaticDataReport":
        _handle_static_data_report(data)
    elif tipo == "SubscriptionConfirmation":
        logger.info("AISstream confirmou a assinatura: %s", data.get("Message"))
    elif "error" in data:
        logger.error("AISstream recusou a assinatura: %s", data)


def _handle_posicao(data: dict, tipo: str) -> None:
    report = data["Message"][tipo]
    meta = data.get("MetaData", {})

    mmsi = meta.get("MMSI")
    latitude = report.get("Latitude")
    longitude = report.get("Longitude")
    # 91 / 181 = posição não disponível
    if mmsi is None or latitude is None or longitude is None or abs(latitude) > 90 or abs(longitude) > 180:
        return

    mmsi = str(mmsi)
    nome = _limpar_texto(meta.get("ShipName")) or _limpar_texto(report.get("Name"))
    anterior = ultimas_posicoes.get(mmsi)
    posicao = {
        "mmsi": mmsi,
        "nome_navio": nome or (anterior or {}).get("nome_navio"),
        "latitude": round(latitude, 5),
        "longitude": round(longitude, 5),
        "velocidade_nos": _ou_none(report.get("Sog"), 102.3),
        "rumo": _ou_none(report.get("Cog"), 360),
        "proa": _ou_none(report.get("TrueHeading"), 360),  # 511 = sem dado
        # Classe B não transmite status de navegação
        "status_navegacao": _ou_none(report.get("NavigationalStatus"), 15),
        "timestamp_utc": _normalizar_time_utc(meta.get("time_utc")),
    }
    ultimas_posicoes[mmsi] = posicao

    agora = time.monotonic()
    if agora - _ultima_gravacao.get(mmsi, -1e9) >= INTERVALO_GRAVACAO_S:
        _ultima_gravacao[mmsi] = agora
        _lote_posicoes.append(posicao)

    # Todo navio com posição entra em navios_info ao menos com o nome, para a
    # busca não precisar varrer a tabela de posições.
    if posicao["nome_navio"] and _nomes_gravados.get(mmsi) != posicao["nome_navio"]:
        _nomes_gravados[mmsi] = posicao["nome_navio"]
        info = {"mmsi": mmsi, "nome_navio": posicao["nome_navio"], "atualizado_em": _agora().isoformat()}
        if tipo == "ExtendedClassBPositionReport":
            info["tipo_codigo"] = report.get("Type") or None
            info["comprimento_m"], info["boca_m"] = _dimensoes(report.get("Dimension"))
        _lote_infos.append(info)


def _handle_ship_static_data(data: dict) -> None:
    static = data.get("Message", {}).get("ShipStaticData", {})
    meta = data.get("MetaData", {})

    mmsi = meta.get("MMSI")
    if mmsi is None:
        return

    comprimento, boca = _dimensoes(static.get("Dimension"))
    eta = static.get("Eta") or {}
    eta_txt = None
    # Mês/dia 0 = não informado; hora 24 / minuto 60 = não informado
    if eta.get("Month") and eta.get("Day") and eta.get("Hour", 24) < 24 and eta.get("Minute", 60) < 60:
        eta_txt = f"{eta['Month']:02d}-{eta['Day']:02d} {eta['Hour']:02d}:{eta['Minute']:02d}"

    _lote_infos.append({
        "mmsi": str(mmsi),
        "nome_navio": _limpar_texto(static.get("Name")) or _limpar_texto(meta.get("ShipName")),
        "imo": str(static["ImoNumber"]) if static.get("ImoNumber") else None,
        "indicativo": _limpar_texto(static.get("CallSign")),
        "tipo_codigo": static.get("Type") or None,
        "comprimento_m": comprimento,
        "boca_m": boca,
        "calado_max_m": static.get("MaximumStaticDraught") or None,
        "destino": _limpar_texto(static.get("Destination")),
        "eta_informada": eta_txt,
        "atualizado_em": _agora().isoformat(),
    })


def _handle_static_data_report(data: dict) -> None:
    """Classe B (mensagem 24): parte A traz o nome; parte B tipo, indicativo e
    dimensões. Chegam em mensagens separadas."""
    corpo = data.get("Message", {}).get("StaticDataReport", {})
    mmsi = data.get("MetaData", {}).get("MMSI")
    if mmsi is None:
        return
    info: dict = {"mmsi": str(mmsi), "atualizado_em": _agora().isoformat()}
    parte_a, parte_b = corpo.get("ReportA") or {}, corpo.get("ReportB") or {}
    if parte_a.get("Valid"):
        info["nome_navio"] = _limpar_texto(parte_a.get("Name"))
    if parte_b.get("Valid"):
        info["tipo_codigo"] = parte_b.get("ShipType") or None
        info["indicativo"] = _limpar_texto(parte_b.get("CallSign"))
        info["comprimento_m"], info["boca_m"] = _dimensoes(parte_b.get("Dimension"))
    if len(info) > 2:
        _lote_infos.append(info)


# ------------------------------------------------------------ tarefas


def _gravar_lote() -> None:
    posicoes, infos = _lote_posicoes[:], _lote_infos[:]
    del _lote_posicoes[: len(posicoes)]
    del _lote_infos[: len(infos)]
    gravar_infos(infos)
    gravar_posicoes(posicoes)


def descartar_navios_antigos() -> int:
    """Tira da memória quem está sem posição há mais de MEMORIA_HORAS (o
    rastro continua no banco)."""
    limite = (_agora() - timedelta(hours=MEMORIA_HORAS)).isoformat()
    antigos = [m for m, p in list(ultimas_posicoes.items()) if p["timestamp_utc"] < limite]
    for mmsi in antigos:
        ultimas_posicoes.pop(mmsi, None)
        _ultima_gravacao.pop(mmsi, None)
        _nomes_gravados.pop(mmsi, None)
    return len(antigos)


def _memoria_mb() -> float | None:
    """Memória residente do processo (Linux: /proc; no Windows fica None)."""
    try:
        with open("/proc/self/status", encoding="ascii") as f:
            for linha in f:
                if linha.startswith("VmRSS:"):
                    return round(int(linha.split()[1]) / 1024, 1)
    except OSError:
        return None
    return None


def _registrar_medicao() -> None:
    global _inicio_medicao
    duracao = time.monotonic() - _inicio_medicao
    total = sum(_contagem_tipos.values())
    descartados = descartar_navios_antigos()
    banco = contar_registros()
    medicao.update({
        "em": _agora().isoformat(),
        "janela_s": round(duracao),
        "msg_por_s": round(total / duracao, 2) if duracao else 0,
        "por_tipo": {t: round(n / duracao, 3) for t, n in _contagem_tipos.most_common()},
        "navios_em_memoria": len(ultimas_posicoes),
        "descartados_6h": descartados,
        "memoria_mb": _memoria_mb(),
        "banco": banco,
    })
    logger.info(
        "Medição AIS: %.2f msg/s em %ds %s | %d navios em memória (%d descartados) | RSS %s MB | banco %s",
        medicao["msg_por_s"], duracao, medicao["por_tipo"], len(ultimas_posicoes), descartados,
        medicao["memoria_mb"], banco,
    )
    _contagem_tipos.clear()
    _inicio_medicao = time.monotonic()


async def tarefa_de_manutencao() -> None:
    """Grava o lote a cada INTERVALO_LOTE_S e registra a medição a cada
    MEDICAO_INTERVALO_S. O SQLite roda numa thread para não travar a API."""
    proxima_medicao = time.monotonic() + MEDICAO_INTERVALO_S
    try:
        while True:
            await asyncio.sleep(INTERVALO_LOTE_S)
            try:
                await asyncio.to_thread(_gravar_lote)
                if time.monotonic() >= proxima_medicao:
                    proxima_medicao = time.monotonic() + MEDICAO_INTERVALO_S
                    await asyncio.to_thread(_registrar_medicao)
            except Exception as exc:  # noqa: BLE001 — banco ocupado não derruba o coletor
                logger.error("Falha ao gravar lote AIS: %s", exc)
    except asyncio.CancelledError:
        await asyncio.to_thread(_gravar_lote)  # não perde o último lote ao desligar
        raise


def _status_http(exc: Exception) -> int | None:
    resposta = getattr(exc, "response", None)
    return getattr(resposta, "status_code", None) or getattr(exc, "status_code", None)


async def escutar_ais_stream() -> None:
    """Loop infinito com reconexão e espera crescente."""
    global conectado
    if not AISSTREAM_API_KEY:
        logger.error(
            "AISSTREAM_API_KEY não configurada. Copie .env.example para .env "
            "e preencha a chave (conta gratuita em https://aisstream.io/)."
        )
        return

    await asyncio.to_thread(carregar_ultimas_posicoes_do_banco)
    espera = 5

    while True:
        periodo_id = None
        inicio_conexao = time.monotonic()
        try:
            async with websockets.connect(AISSTREAM_URL, open_timeout=15, max_size=2**22) as ws:
                await ws.send(json.dumps({
                    "APIKey": AISSTREAM_API_KEY,
                    "BoundingBoxes": AIS_CAIXAS,
                    "FilterMessageTypes": [*TIPOS_POSICAO, *TIPOS_ESTATICOS],
                }))
                periodo_id = await asyncio.to_thread(abrir_periodo_coleta, _agora().isoformat())
                conectado = True
                logger.info("Conectado ao AISstream (%d caixa(s): %s).", len(AIS_CAIXAS), AIS_CAIXAS)
                ultimo_sinal = time.monotonic()
                while True:
                    # recv() com timeout em vez de "async for": o período de
                    # coleta é atualizado mesmo quando não chega mensagem.
                    try:
                        _handle_message(await asyncio.wait_for(ws.recv(), timeout=INTERVALO_SINAL_S))
                    except TimeoutError:
                        pass
                    if time.monotonic() - ultimo_sinal >= INTERVALO_SINAL_S:
                        ultimo_sinal = time.monotonic()
                        await asyncio.to_thread(registrar_sinal_coleta, periodo_id, _agora().isoformat())
                        if time.monotonic() - inicio_conexao > 300:
                            espera = 5  # conexão estável: zera a espera
        except asyncio.CancelledError:
            conectado = False
            if periodo_id:
                fechar_periodo_coleta(periodo_id, _agora().isoformat(), "backend encerrado")
            logger.info("Coletor AIS encerrado; conexão fechada.")
            raise
        except Exception as exc:  # noqa: BLE001 — reconecta em vez de derrubar o backend inteiro
            conectado = False
            if periodo_id:
                await asyncio.to_thread(fechar_periodo_coleta, periodo_id, _agora().isoformat(), f"erro: {exc}"[:200])
            if _status_http(exc) == 429:
                espera = max(espera, 60)
                logger.warning("AISstream recusou (429): outra conexão com a mesma chave ainda aberta. "
                               "Nova tentativa em %ds.", espera)
            else:
                logger.error("Conexão com AISstream falhou: %s. Nova tentativa em %ds.", exc, espera)
            await asyncio.sleep(espera)
            espera = min(espera * 2, 300)


if __name__ == "__main__":
    from storage import inicializar_banco

    async def _main():
        await asyncio.gather(escutar_ais_stream(), tarefa_de_manutencao())

    inicializar_banco()
    try:
        asyncio.run(_main())
    except KeyboardInterrupt:
        logger.info("Encerrado pelo usuário.")
