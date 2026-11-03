"""
Backend do Info-Maré — FastAPI.

Junta num só processo (um único event loop):
  - Coletor AIS em background (ais_stream.py): todos os navios da caixa,
    última posição em memória, gravação limitada no SQLite
  - Agendador (praticagem a cada 15 min, índice operacional + alertas a cada
    30 min, limpeza de posições com mais de 7 dias 1x/dia)
  - API REST de leitura
  - O painel compilado (exportação estática do Next em painel/out), servido
    na mesma URL — um serviço só no Render, sem CORS entre domínios

Os endpoints são públicos e só de leitura. Em vez de chave de API (que no
navegador não protege nada), há limite de requisições por IP. Nenhuma chave
chega ao navegador.

Rodar:
    uvicorn backend_app:app --port 8000
"""

import asyncio
import os
import pathlib
import threading
import time
from collections import defaultdict
from contextlib import asynccontextmanager
from dataclasses import asdict
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

import ais_stream
from config.port_operations_config import NOS_PARA_KMH, PORT_CONFIGS
from scheduler import job_atualizar_praticagem, job_monitorar_saude_do_sistema, job_recalcular_indice_operacional
from storage import (
    apagar_posicoes_antigas,
    buscar_navios,
    inicializar_banco,
    listar_alertas_recentes,
    listar_alertas_por_porto,
    listar_periodos_coleta,
    obter_eventos_mudanca_status,
    obter_fila_manobras,
    obter_historico_indice,
    obter_info_navios_por_mmsi,
    obter_trajetoria,
    obter_ultima_barra_status,
    obter_ultimo_indice_por_porto,
)
from referencias_ais import bandeira_por_mmsi, nome_status, nome_tipo
from eta import calcular_eta
from tide_now import (
    agora_brasilia,
    altura_mare_agora,
    curva_do_dia,
    eventos_formatados,
    fonte_da_tabua,
    hoje_brasilia,
    status_mare_agora,
)
from mare_ciclo import proximos_picos
from tide_utils import classificar_coeficiente, coeficiente_por_fase_lunar, idade_da_lua, fase_da_lua
from sea_conditions import buscar_condicoes_operacionais, buscar_previsao_diaria, buscar_serie_horaria
from proximos_dias import resumo_proximos_dias
from monitoramento import checar_saude_do_sistema
from praticagem import porto_tem_fonte_de_praticagem, porto_tem_fila_de_manobras
from sun_times import nascer_por_do_sol
from draft_calculator import calcular_janelas_seguras
from nivel_rio_manaus import buscar_calados_manaus, buscar_nivel_rio_manaus
from painel_porto import MANAUS, painel_manaus, painel_porto, resumo_portos, todos_os_slugs
from port_operations import (
    classificar_indice_5_faixas,
    construir_pontos_operacionais,
    resumir_janela_operacional,
)

# Calculadora de calado DESLIGADA até existir, por porto, a profundidade do
# canal referida ao Nível de Redução (NR) — normalmente na NPCP da Capitania.
# A versão anterior usava o nível médio da maré no lugar e nunca achava janela.
CALCULADORA_CALADO_ATIVA = os.getenv("CALCULADORA_CALADO_ATIVA", "0") == "1"

# Painel compilado (npm run build em painel/). Sem a pasta, só a API sobe.
PAINEL_DIR = pathlib.Path(os.getenv("PAINEL_DIR") or pathlib.Path(__file__).parent.parent / "painel" / "out")

agendador = AsyncIOScheduler(timezone="UTC")
_tarefas: list[asyncio.Task] = []


def job_limpar_posicoes_antigas() -> None:
    apagadas = apagar_posicoes_antigas(dias=7)
    print(f"[{datetime.now(timezone.utc).isoformat()}] Limpeza AIS: {apagadas} posições com mais de 7 dias apagadas")


@asynccontextmanager
async def lifespan(app: FastAPI):
    inicializar_banco()

    # Jobs bloqueantes (requests) rodam no threadpool do AsyncIOScheduler,
    # sem travar o event loop do FastAPI.
    agora = datetime.now(timezone.utc)
    # Índice e saúde começam 2 min depois — dá tempo da maré/praticagem/AIS
    # chegarem, senão o 1º ciclo pula todos os portos e só refaz em 30 min.
    depois_da_coleta = agora + timedelta(minutes=2)
    agendador.add_job(job_atualizar_praticagem, "interval", minutes=15, next_run_time=agora)
    agendador.add_job(
        job_recalcular_indice_operacional, "interval", minutes=30, next_run_time=depois_da_coleta
    )
    agendador.add_job(job_monitorar_saude_do_sistema, "interval", minutes=30, next_run_time=depois_da_coleta)
    agendador.add_job(job_limpar_posicoes_antigas, "interval", hours=24, next_run_time=depois_da_coleta)
    agendador.start()

    _tarefas.append(asyncio.create_task(ais_stream.escutar_ais_stream()))
    _tarefas.append(asyncio.create_task(ais_stream.tarefa_de_manutencao()))

    yield

    agendador.shutdown(wait=False)
    # Espera o coletor fechar o WebSocket: o AISstream só aceita um coletor por
    # chave, e a próxima instância (deploy/reinício) precisa da vaga.
    for tarefa in _tarefas:
        tarefa.cancel()
    await asyncio.wait(_tarefas, timeout=10)


app = FastAPI(title="Info-Maré", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

# CORS só faz falta em desenvolvimento (painel em :3000, API em :8000). Em
# produção o painel vem da mesma origem: deixe CORS_ALLOW_ORIGINS vazio.
_cors_origins = [o.strip() for o in os.getenv("CORS_ALLOW_ORIGINS", "").split(",") if o.strip() and o.strip() != "*"]
if _cors_origins:
    app.add_middleware(CORSMiddleware, allow_origins=_cors_origins, allow_methods=["GET"], allow_headers=[])

app.add_middleware(GZipMiddleware, minimum_size=1000)

# --- Limite de requisições por IP (janela deslizante de 60 s, em memória) ---
# Dois limites: API (consultas) e arquivos do painel (uma abertura de página
# baixa dezenas de arquivos).
LIMITE_REQ_POR_MIN = int(os.getenv("LIMITE_REQ_POR_MIN", "120"))
LIMITE_ARQUIVOS_POR_MIN = int(os.getenv("LIMITE_ARQUIVOS_POR_MIN", "600"))
# Atrás de proxy (Render, Cloudflare) o IP real vem no X-Forwarded-For.
# Só confie nesse header se o backend NÃO estiver exposto direto.
CONFIAR_X_FORWARDED_FOR = os.getenv("CONFIAR_X_FORWARDED_FOR", "0") == "1"
_requisicoes: dict[tuple[str, str], list[float]] = defaultdict(list)
_requisicoes_lock = threading.Lock()


@app.middleware("http")
async def limitar_requisicoes(request: Request, call_next):
    caminho = request.url.path
    if caminho == "/health" or request.method == "OPTIONS":
        return await call_next(request)
    ip = request.client.host if request.client else "?"
    if CONFIAR_X_FORWARDED_FOR and request.headers.get("x-forwarded-for"):
        ip = request.headers["x-forwarded-for"].split(",")[0].strip()
    grupo, limite = ("api", LIMITE_REQ_POR_MIN) if caminho.startswith("/api/") else ("arq", LIMITE_ARQUIVOS_POR_MIN)
    chave = (ip, grupo)
    agora = time.monotonic()
    with _requisicoes_lock:
        janela = [t for t in _requisicoes[chave] if agora - t < 60]
        if len(janela) >= limite:
            _requisicoes[chave] = janela
            return JSONResponse({"detail": "Muitas consultas seguidas. Aguarde meio minuto e tente de novo."},
                                status_code=429, headers={"Retry-After": "30"})
        janela.append(agora)
        _requisicoes[chave] = janela
        if len(_requisicoes) > 10_000:  # não deixa a tabela de IPs crescer sem limite
            for k in [k for k, v in _requisicoes.items() if not v or agora - v[-1] >= 60]:
                del _requisicoes[k]
    resposta = await call_next(request)
    resposta.headers.setdefault("X-Content-Type-Options", "nosniff")
    resposta.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    if caminho.startswith("/_next/static/"):
        resposta.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    return resposta


@app.get("/health")
def health():
    """Leve de propósito: é o que o pinger externo chama a cada 5 min."""
    return {"status": "ok", "ais_conectado": ais_stream.conectado}


def _idade_segundos(timestamp_iso: str | None) -> int | None:
    if not timestamp_iso:
        return None
    try:
        return int((datetime.now(timezone.utc) - datetime.fromisoformat(timestamp_iso)).total_seconds())
    except ValueError:
        return None


def _armador(info: dict) -> dict:
    """Armador só com fonte registrada — nunca inferido do nome."""
    if info.get("armador") and info.get("armador_fonte"):
        return {"nome": info["armador"], "fonte": info["armador_fonte"], "em": info.get("armador_em")}
    return {"nome": None, "fonte": None, "em": None}


CAMPOS_NAVIO = ["mmsi", "lat", "lon", "velocidade", "rumo", "proa", "status", "nome", "idade_s"]
_cache_mapa: tuple[float, list[list]] | None = None
_cache_mapa_lock = threading.Lock()


def _instantaneo_navios() -> list[list]:
    """Todos os navios em memória como arrays compactos. Refeito no máximo a
    cada 5 s: várias pessoas olhando o mapa não multiplicam o trabalho."""
    global _cache_mapa
    with _cache_mapa_lock:
        if _cache_mapa and time.monotonic() - _cache_mapa[0] < 5:
            return _cache_mapa[1]
        agora = datetime.now(timezone.utc)
        linhas = [
            [p["mmsi"], p["latitude"], p["longitude"], p.get("velocidade_nos"), p.get("rumo"), p.get("proa"),
             p.get("status_navegacao"), p.get("nome_navio"),
             int((agora - datetime.fromisoformat(p["timestamp_utc"])).total_seconds())]
            for p in list(ais_stream.ultimas_posicoes.values())
        ]
        _cache_mapa = (time.monotonic(), linhas)
        return linhas


def _ler_bbox(bbox: str | None) -> tuple[float, float, float, float] | None:
    if not bbox:
        return None
    try:
        lon_min, lat_min, lon_max, lat_max = (float(v) for v in bbox.split(","))
    except ValueError:
        raise HTTPException(status_code=422, detail="bbox deve ser lonmin,latmin,lonmax,latmax")
    if not (-180 <= lon_min <= 180 and -180 <= lon_max <= 180 and -90 <= lat_min <= lat_max <= 90):
        raise HTTPException(status_code=422, detail="bbox fora dos limites")
    return lon_min, lat_min, lon_max, lat_max


@app.get("/api/navios")
def navios_no_mapa(bbox: str | None = None):
    """Última posição de cada navio (memória, até 6 h) dentro da área visível.
    Resposta compacta: lista de arrays na ordem de "campos"."""
    linhas = _instantaneo_navios()
    caixa = _ler_bbox(bbox)
    if caixa:
        lon_min, lat_min, lon_max, lat_max = caixa
        if lon_min <= lon_max:
            linhas = [n for n in linhas if lat_min <= n[1] <= lat_max and lon_min <= n[2] <= lon_max]
        else:  # caixa cruzando o antimeridiano
            linhas = [n for n in linhas if lat_min <= n[1] <= lat_max and (n[2] >= lon_min or n[2] <= lon_max)]
    return {
        "campos": CAMPOS_NAVIO,
        "navios": linhas,
        "total_memoria": len(ais_stream.ultimas_posicoes),
        "gerado_em": datetime.now(timezone.utc).isoformat(),
        "fonte": "AISstream.io (antenas terrestres)",
    }


@app.get("/api/navios/busca")
def busca_navios(q: str = Query(min_length=3, max_length=40)):
    """Busca por nome (parcial), MMSI ou IMO entre os navios já vistos — até 20."""
    resultado = []
    for n in buscar_navios(q, limite=20):
        resultado.append({
            "mmsi": n["mmsi"],
            "nome": n.get("nome_navio"),
            "imo": n.get("imo"),
            "tipo": nome_tipo(n.get("tipo_codigo")),
            "bandeira": bandeira_por_mmsi(n["mmsi"]),
            "tem_posicao": n["mmsi"] in ais_stream.ultimas_posicoes,
        })
    return resultado


@app.get("/api/navios/lote")
def navios_em_lote(mmsi: str = Query(max_length=10 * 200)):
    """Situação dos "Meus navios" numa chamada só (até 200 MMSI separados por
    vírgula): nome, IMO, status, velocidade, destino e idade da posição."""
    lista = list(dict.fromkeys(m for m in mmsi.split(",") if m.isdigit() and len(m) == 9))[:200]
    infos = obter_info_navios_por_mmsi(lista)
    agora = datetime.now(timezone.utc)
    resultado = []
    for m in lista:
        info, p = infos.get(m, {}), ais_stream.ultimas_posicoes.get(m)
        resultado.append({
            "mmsi": m,
            "nome": info.get("nome_navio") or (p or {}).get("nome_navio"),
            "imo": info.get("imo"),
            "destino_informado": info.get("destino"),
            "status_codigo": (p or {}).get("status_navegacao"),
            "velocidade_nos": (p or {}).get("velocidade_nos"),
            "latitude": (p or {}).get("latitude"),
            "longitude": (p or {}).get("longitude"),
            # sem posição em memória (>6 h): a idade vem do último registro no banco
            "idade_s": int((agora - datetime.fromisoformat(p["timestamp_utc"])).total_seconds()) if p else None,
        })
    sem_posicao = [r for r in resultado if r["idade_s"] is None]
    for r in sem_posicao:
        ultima = obter_trajetoria(r["mmsi"], limite=1, horas=24 * 7, mais_recentes=True)
        if ultima:
            r.update(latitude=ultima[0]["latitude"], longitude=ultima[0]["longitude"],
                     idade_s=_idade_segundos(ultima[0]["timestamp_utc"]))
    return resultado


def _validar_mmsi(mmsi: str) -> None:
    if not (mmsi.isdigit() and len(mmsi) == 9):
        raise HTTPException(status_code=422, detail="MMSI tem 9 dígitos")


@app.get("/api/navios/{mmsi}")
def card_navio(mmsi: str):
    """Card do navio: dados estáticos (AIS), última posição e idade dela."""
    _validar_mmsi(mmsi)
    info = obter_info_navios_por_mmsi([mmsi]).get(mmsi, {})
    posicao = ais_stream.ultimas_posicoes.get(mmsi)
    if posicao is None:  # fora da memória (>6 h): última posição gravada
        ultimas = obter_trajetoria(mmsi, limite=1, horas=24 * 7, mais_recentes=True)
        posicao = {**ultimas[0], "mmsi": mmsi} if ultimas else None
    if not info and not posicao:
        raise HTTPException(status_code=404, detail=f"Navio MMSI {mmsi} ainda não visto pelo AIS")

    return {
        "mmsi": mmsi,
        "nome": info.get("nome_navio") or (posicao or {}).get("nome_navio"),
        "imo": info.get("imo"),
        "indicativo": info.get("indicativo"),
        "tipo": nome_tipo(info.get("tipo_codigo")),
        "tipo_codigo": info.get("tipo_codigo"),
        "comprimento_m": info.get("comprimento_m"),
        "boca_m": info.get("boca_m"),
        "calado_max_m": info.get("calado_max_m"),
        "bandeira": bandeira_por_mmsi(mmsi),
        "destino_informado": info.get("destino"),
        "eta_informada": info.get("eta_informada"),  # "MM-DD HH:MM" UTC, sem ano (limitação do AIS)
        "armador": _armador(info),
        "dados_estaticos_em": info.get("atualizado_em"),
        "posicao": None if not posicao else {
            "latitude": posicao["latitude"],
            "longitude": posicao["longitude"],
            "velocidade_nos": posicao.get("velocidade_nos"),
            "rumo": posicao.get("rumo"),
            "proa": posicao.get("proa"),
            "status": nome_status(posicao.get("status_navegacao")),
            "status_codigo": posicao.get("status_navegacao"),
            "timestamp_utc": posicao["timestamp_utc"],
            "idade_s": _idade_segundos(posicao["timestamp_utc"]),
        },
        "fonte": "AISstream.io (antenas terrestres)",
    }


@app.get("/api/sistema/coleta-ais")
def periodos_coleta_ais(dias: int = 7):
    """Períodos em que o listener AIS estava conectado. Fora deles, falta de
    posição é lacuna de coleta (o AIS não tem histórico)."""
    return listar_periodos_coleta(dias=dias)


@app.get("/api/portos")
def listar_portos():
    indices = obter_ultimo_indice_por_porto()
    resultado = []
    for slug, cfg in PORT_CONFIGS.items():
        info = indices.get(cfg.porto)
        resultado.append({
            "slug": slug,
            "porto": cfg.porto,
            "estado": cfg.estado,
            "lat": cfg.lat,
            "lon": cfg.lon,
            "calado_maximo_m": cfg.calado_maximo_m,
            "indice_operacional": info["indice"] if info else None,
            "status": info["status"] if info else None,
            "calculado_em": info["calculado_em"] if info else None,
            "modelo": "mare",
        })

    # Manaus: fora de PORT_CONFIGS de propósito (ver nota no config) — entra
    # com outro "modelo": não tem maré/índice operacional, só nível de rio.
    resultado.append({
        **MANAUS,
        "calado_maximo_m": None,
        "indice_operacional": None,
        "status": None,
        "calculado_em": None,
        "modelo": "nivel_rio",
    })
    return resultado


_cache_nivel_rio: tuple[float, dict] | None = None


def _nivel_rio_em_cache() -> dict:
    """Cache de 15 min — as fontes atualizam no máximo a cada 15 min e o
    serviço da ANA pede frequência baixa."""
    global _cache_nivel_rio
    if _cache_nivel_rio and time.monotonic() - _cache_nivel_rio[0] < 900:
        return _cache_nivel_rio[1]
    dados = buscar_nivel_rio_manaus().to_dict()
    if dados["disponivel"]:
        _cache_nivel_rio = (time.monotonic(), dados)
    return dados


_cache_calados: tuple[float, dict] | None = None


def _calados_manaus_em_cache() -> dict | None:
    """Calados dos berços de Manaus: o porto publica uma vez por dia."""
    global _cache_calados
    if _cache_calados and time.monotonic() - _cache_calados[0] < 1800:
        return _cache_calados[1]
    dados = buscar_calados_manaus()
    if dados:
        _cache_calados = (time.monotonic(), dados)
    return dados


@app.get("/api/portos/manaus/nivel-rio")
def nivel_rio_manaus():
    """Manaus é porto fluvial (ver nivel_rio_manaus.py): nível do rio, não maré."""
    return _nivel_rio_em_cache()


@app.get("/api/portos/resumo")
def resumo(slugs: str = Query(default="", max_length=400)):
    """Tela Resumo: uma linha por porto pedido (todos, se vazio)."""
    validos = set(todos_os_slugs())
    pedidos = [s for s in slugs.split(",") if s in validos] or todos_os_slugs()
    return resumo_portos(pedidos[:20], _nivel_rio_em_cache, _calados_manaus_em_cache)


_cache_painel: dict[str, tuple[float, dict]] = {}


@app.get("/api/portos/{slug}/painel")
def painel_do_porto(slug: str):
    """Tudo o que o painel do porto mostra, numa chamada: situação, índice
    (com a explicação), maré, vento/onda, barra, calado com fonte, navios.
    Cache de 30 s por porto."""
    item = _cache_painel.get(slug)
    if item and time.monotonic() - item[0] < 30:
        return item[1]
    dados = painel_manaus(_nivel_rio_em_cache, _calados_manaus_em_cache) if slug == "manaus" else painel_porto(slug)
    if dados is None:
        raise HTTPException(status_code=404, detail=f"Porto '{slug}' não encontrado")
    dados["gerado_em"] = datetime.now(timezone.utc).isoformat()
    _cache_painel[slug] = (time.monotonic(), dados)
    return dados


@app.get("/api/portos/{slug}")
def detalhe_porto(slug: str):
    cfg = PORT_CONFIGS.get(slug)
    if cfg is None:
        raise HTTPException(status_code=404, detail=f"Porto '{slug}' não encontrado")

    indices = obter_ultimo_indice_por_porto()
    info = indices.get(cfg.porto)
    mare_agora = altura_mare_agora(cfg.dhn_id) if cfg.dhn_id else None

    return {
        "slug": slug,
        "porto": cfg.porto,
        "lat": cfg.lat,
        "lon": cfg.lon,
        "calado_maximo_m": cfg.calado_maximo_m,
        "calado_confianca": cfg.calado_confianca,
        "canal": cfg.canal,
        "berços": cfg.berços or None,
        "zona_praticagem": cfg.zona_praticagem,
        "fonte_oficial": cfg.fonte_oficial,
        "ultima_verificacao": cfg.ultima_verificacao,
        # limite mais restritivo com fonte (pros gráficos); None = sem dado
        "onda_limite_m": cfg.limite_mais_restritivo("onda_hs_m"),
        "vento_limite_kmh": (
            round(cfg.limite_mais_restritivo("vento_kn") * NOS_PARA_KMH, 1)
            if cfg.limite_mais_restritivo("vento_kn") is not None else None
        ),
        "limites": [asdict(lim) for lim in cfg.limites],
        "indice_calculavel": cfg.indice_calculavel,
        "calculadora_calado_ativa": CALCULADORA_CALADO_ATIVA,
        "mare_atual_m": mare_agora,
        "indice_operacional": info["indice"] if info else None,
        "status": info["status"] if info else None,
        "calculado_em": info["calculado_em"] if info else None,
    }


@app.get("/api/alertas")
def alertas_recentes(limite: int = 30):
    return listar_alertas_recentes(limite=limite)


@app.get("/api/portos/{slug}/mare")
def detalhe_mare(slug: str):
    """Status atual da maré, coeficiente, próximos picos, curva do dia,
    janela operacional (com barra de progresso) e gauge de 5 faixas."""
    cfg = PORT_CONFIGS.get(slug)
    if cfg is None:
        raise HTTPException(status_code=404, detail=f"Porto '{slug}' não encontrado")

    coeficiente = coeficiente_por_fase_lunar(idade_da_lua())
    curva = curva_do_dia(cfg.dhn_id) if cfg.dhn_id else []

    # Janela operacional: usa vento/onda atuais aplicados ao dia todo
    # (simplificação — TODO: usar série horária real de vento/onda quando
    # tivermos previsão hora a hora armazenada, não só o valor atual)
    # Janela/índice só com parâmetros com fonte (cfg.indice_calculavel)
    condicoes_op = buscar_condicoes_operacionais(cfg.lat, cfg.lon) if cfg.indice_calculavel else None
    pontos_operacionais = (
        construir_pontos_operacionais(curva, cfg, condicoes_op.weather.vento_kmh, condicoes_op.onda_altura_m)
        if condicoes_op and curva else []
    )
    # Curva de maré está em hora de Brasília (DHN) — a hora atual também precisa estar
    hora_atual_str = agora_brasilia().strftime("%H:%M")
    janela = resumir_janela_operacional(pontos_operacionais, hora_atual_str) if pontos_operacionais else None

    # Último ponto da curva que já passou (não o primeiro do dia, 00:00)
    indice_atual = next((p["indice"] for p in reversed(pontos_operacionais) if p["hora"] <= hora_atual_str), None)

    return {
        "slug": slug,
        "porto": cfg.porto,
        "mare_atual_m": altura_mare_agora(cfg.dhn_id) if cfg.dhn_id else None,
        "status": status_mare_agora(cfg.dhn_id) if cfg.dhn_id else None,
        "coeficiente_atual": coeficiente,
        "classificacao_coeficiente": classificar_coeficiente(coeficiente),
        "curva_hoje": curva,
        "fonte": fonte_da_tabua(cfg.dhn_id) if cfg.dhn_id else None,
        # preamares/baixamares reais da DHN (a curva é interpolada entre eles)
        "eventos_hoje": eventos_formatados(cfg.dhn_id, hoje_brasilia()) if cfg.dhn_id else [],
        "hora_atual": hora_atual_str,
        "janela_operacional": janela,
        "indice_operacional_gauge": {
            "valor": indice_atual,
            **(classificar_indice_5_faixas(indice_atual) if indice_atual is not None else {"label": None, "cor": None}),
        },
        "proximas_sizigias": [
            {"data": p.data.isoformat(), "coeficiente": p.coeficiente}
            for p in proximos_picos("viva", dias=30)[:3]
        ],
        "proximas_quadraturas": [
            {"data": p.data.isoformat(), "coeficiente": p.coeficiente}
            for p in proximos_picos("morta", dias=30)[:3]
        ],
    }


@app.get("/api/portos/{slug}/condicoes")
def condicoes_porto(slug: str):
    """Condições meteorológicas + do mar, no formato dos cards do painel."""
    cfg = PORT_CONFIGS.get(slug)
    if cfg is None:
        raise HTTPException(status_code=404, detail=f"Porto '{slug}' não encontrado")

    condicoes = buscar_condicoes_operacionais(cfg.lat, cfg.lon)
    return {
        "slug": slug,
        "fonte": "Open-Meteo (CC BY 4.0) — previsão de modelo",
        "obtido_em": condicoes.obtido_em,
        "onda_altura_m": condicoes.onda_altura_m,
        "onda_periodo_s": condicoes.onda_periodo_s,
        "onda_direcao_deg": condicoes.onda_direcao_deg,
        "onda_proximas_24h": condicoes.onda_proximas_24h,
        "weather": {
            "temperatura_c": condicoes.weather.temperatura_c,
            "vento_kmh": condicoes.weather.vento_kmh,
            "vento_direcao_deg": condicoes.weather.vento_direcao_deg,
            "probabilidade_chuva_pct": condicoes.weather.probabilidade_chuva_pct,
            "umidade_pct": condicoes.weather.umidade_pct,
            "pressao_hpa": condicoes.weather.pressao_hpa,
            "visibilidade_km": condicoes.weather.visibilidade_km,
        },
    }


@app.get("/api/portos/{slug}/info")
def info_porto(slug: str):
    """Informações estáticas do porto: localização, fuso, nascer/pôr do
    sol, fase da lua — bloco 'Informações do Porto' do layout de referência."""
    cfg = PORT_CONFIGS.get(slug)
    if cfg is None:
        raise HTTPException(status_code=404, detail=f"Porto '{slug}' não encontrado")

    hoje = datetime.now(timezone.utc)
    sol = nascer_por_do_sol(hoje.year, hoje.month, hoje.day, cfg.lat, cfg.lon)
    lua = fase_da_lua(idade_da_lua())

    return {
        "slug": slug,
        "porto": cfg.porto,
        "estado": cfg.estado,
        "lat": cfg.lat,
        "lon": cfg.lon,
        "fuso_horario": "UTC-3 (Brasília)",
        "nascer_do_sol": sol["nascer"],
        "por_do_sol": sol["por"],
        "fase_da_lua": lua,
    }


@app.get("/api/portos/{slug}/calculadora-calado")
def calculadora_calado(slug: str, calado: float, margem: float = 0.5):
    """UKC — janelas seguras de passagem pro calado informado."""
    cfg = PORT_CONFIGS.get(slug)
    if cfg is None:
        raise HTTPException(status_code=404, detail=f"Porto '{slug}' não encontrado")
    if not CALCULADORA_CALADO_ATIVA:
        raise HTTPException(
            status_code=503,
            detail="Calculadora de calado desligada: falta a profundidade do canal referida ao NR para este porto.",
        )
    if not cfg.dhn_id:
        raise HTTPException(status_code=422, detail=f"Porto '{slug}' sem dhn_id configurado")

    curva = curva_do_dia(cfg.dhn_id)
    return calcular_janelas_seguras(cfg.dhn_id, curva, calado_navio_m=calado, margem_ukc_m=margem)


@app.get("/api/portos/{slug}/proximos-dias")
def proximos_dias(slug: str, dias: int = 4):
    """Resumo dos próximos N dias: maior/menor maré, índice, status e
    janela de entrada — bloco 'Próximos dias' do layout de referência."""
    cfg = PORT_CONFIGS.get(slug)
    if cfg is None:
        raise HTTPException(status_code=404, detail=f"Porto '{slug}' não encontrado")
    if not cfg.dhn_id:
        raise HTTPException(status_code=422, detail=f"Porto '{slug}' sem dhn_id configurado")

    previsao = buscar_previsao_diaria(cfg.lat, cfg.lon, dias=dias)
    resumo = resumo_proximos_dias(cfg, previsao, dias=dias)
    return [
        {
            "data": r.data, "label": r.label, "maior_mare_m": r.maior_mare_m,
            "menor_mare_m": r.menor_mare_m, "indice": r.indice, "status": r.status,
            "janela_a_partir": r.janela_a_partir,
        }
        for r in resumo
    ]


@app.get("/api/portos/{slug}/historico")
def historico_porto(slug: str):
    """Bloco 'Histórico': últimas marés (ontem), últimos alertas e
    últimos eventos (mudança de status, derivada do próprio histórico
    de índice operacional gravado a cada ciclo do scheduler)."""
    cfg = PORT_CONFIGS.get(slug)
    if cfg is None:
        raise HTTPException(status_code=404, detail=f"Porto '{slug}' não encontrado")

    ontem = hoje_brasilia() - timedelta(days=1)
    mares_ontem = eventos_formatados(cfg.dhn_id, ontem) if cfg.dhn_id else []

    return {
        "slug": slug,
        "mares_ontem": mares_ontem,
        "ultimos_alertas": listar_alertas_por_porto(cfg.porto, limite=10),
        "ultimos_eventos": obter_eventos_mudanca_status(cfg.porto, limite=10),
    }


@app.get("/api/portos/{slug}/barra")
def barra_porto(slug: str):
    """Condição de barra confirmada pela praticagem (só disponível pra
    portos com fonte pública confirmada — hoje Santos e Rio Grande)."""
    cfg = PORT_CONFIGS.get(slug)
    if cfg is None:
        raise HTTPException(status_code=404, detail=f"Porto '{slug}' não encontrado")

    if not porto_tem_fonte_de_praticagem(cfg.porto):
        return {"slug": slug, "disponivel": False, "situacao": None, "fonte": None, "coletado_em": None}

    barra = obter_ultima_barra_status(cfg.porto)
    if barra is None:
        return {"slug": slug, "disponivel": True, "situacao": None, "fonte": None, "coletado_em": None}

    return {
        "slug": slug,
        "disponivel": True,
        "situacao": barra["situacao"],
        "fechada": bool(barra["fechada"]),
        "fonte": barra["fonte"],
        "desde": barra["desde"],
        "coletado_em": barra["coletado_em"],
    }


@app.get("/api/portos/{slug}/fila-navios")
def fila_navios(slug: str):
    """Fila de manobras (entrada/saída/movimentação de berço) — só
    disponível pra portos com fonte confirmada (hoje só Rio Grande)."""
    cfg = PORT_CONFIGS.get(slug)
    if cfg is None:
        raise HTTPException(status_code=404, detail=f"Porto '{slug}' não encontrado")

    if not porto_tem_fila_de_manobras(cfg.porto):
        return {"slug": slug, "disponivel": False, "manobras": []}

    manobras = obter_fila_manobras(cfg.porto)
    return {
        "slug": slug,
        "disponivel": True,
        "manobras": [
            {
                "navio": m["navio"], "tipo_manobra": m["tipo_manobra"],
                "manobra_de": m["manobra_de"], "manobra_para": m["manobra_para"],
                "previsao": m["previsao"],
            }
            for m in manobras
        ],
    }


@app.get("/api/navios/{mmsi}/trajetoria")
def trajetoria_navio(mmsi: str, horas: int = Query(default=24, ge=1, le=168)):
    """Rastro do navio (últimas N horas, no máximo 1 ponto por minuto) para
    desenhar a linha no mapa."""
    _validar_mmsi(mmsi)
    posicoes = obter_trajetoria(mmsi, horas=horas)
    return {
        "type": "LineString",
        "coordinates": [[p["longitude"], p["latitude"]] for p in posicoes],
        "inicio": posicoes[0]["timestamp_utc"] if posicoes else None,
        "fim": posicoes[-1]["timestamp_utc"] if posicoes else None,
    }


@app.get("/api/navios/{mmsi}/eta/{slug_porto}")
def eta_navio(mmsi: str, slug_porto: str):
    """ETA estimado (linha reta / velocidade atual) do navio até um porto
    específico. Retorna null se o navio não tiver posição recente ou
    estiver praticamente parado (estimativa não confiável nesse caso)."""
    cfg = PORT_CONFIGS.get(slug_porto)
    if cfg is None:
        raise HTTPException(status_code=404, detail=f"Porto '{slug_porto}' não encontrado")

    ultima = ais_stream.ultimas_posicoes.get(mmsi)
    if ultima is None:
        return {"mmsi": mmsi, "disponivel": False, "motivo": "sem posição recente"}

    estimativa = calcular_eta(
        ultima["latitude"], ultima["longitude"], ultima["velocidade_nos"], cfg.lat, cfg.lon
    )
    if estimativa is None:
        return {"mmsi": mmsi, "disponivel": False, "motivo": "navio parado ou sem velocidade suficiente"}

    return {
        "mmsi": mmsi,
        "porto": cfg.porto,
        "disponivel": True,
        "distancia_km": estimativa.distancia_km,
        "velocidade_nos": estimativa.velocidade_nos,
        "horas_estimadas": estimativa.horas_estimadas,
        "confiabilidade": estimativa.confiabilidade,
    }


@app.get("/api/portos/{slug}/historico-indice")
def historico_indice_porto(slug: str, dias: int = 7):
    """Série histórica do índice operacional — alimenta o gráfico de
    tendência (últimos dias/semanas) na página do porto."""
    cfg = PORT_CONFIGS.get(slug)
    if cfg is None:
        raise HTTPException(status_code=404, detail=f"Porto '{slug}' não encontrado")

    return obter_historico_indice(cfg.porto, dias=dias)


@app.get("/api/sistema/saude")
def saude_do_sistema():
    """Diagnóstico das fontes de dado (AIS, praticagem, maré) e a medição do
    coletor (mensagens por segundo, navios em memória, memória, banco)."""
    problemas = checar_saude_do_sistema()
    return {
        "ok": len(problemas) == 0,
        "problemas": [{"fonte": p.fonte, "mensagem": p.mensagem} for p in problemas],
        "ais": {"conectado": ais_stream.conectado, "navios_em_memoria": len(ais_stream.ultimas_posicoes),
                "ultima_medicao": ais_stream.medicao or None},
    }


@app.get("/api/portos/{slug}/previsao-detalhada")
def previsao_detalhada(slug: str, dias: int = 5):
    """Série horária de vento/rajada/onda/período dos próximos dias —
    alimenta os gráficos de vento e onda que faltavam (equivalente à
    seção 'previsão detalhada' do MaréAgora)."""
    cfg = PORT_CONFIGS.get(slug)
    if cfg is None:
        raise HTTPException(status_code=404, detail=f"Porto '{slug}' não encontrado")

    return buscar_serie_horaria(cfg.lat, cfg.lon, dias=dias)


class PainelEstatico(StaticFiles):
    """O Next 16 exporta os dados de navegação em "__next.portos/__PAGE__.txt",
    mas o navegador pede "__next.portos.__PAGE__.txt". Sem este ajuste cada
    clique entre telas recarregava a página inteira."""

    def lookup_path(self, path: str):
        caminho, info = super().lookup_path(path)
        nome = os.path.basename(path)
        if info is None and nome.startswith("__next.") and ".__" in nome[7:]:
            corte = path.rfind(".__")
            return super().lookup_path(path[:corte] + "/" + path[corte + 1:])
        return caminho, info


# Painel compilado por último: as rotas /api e /health acima têm prioridade.
if PAINEL_DIR.is_dir():
    app.mount("/", PainelEstatico(directory=PAINEL_DIR, html=True), name="painel")
else:
    print(f"Painel compilado não encontrado em {PAINEL_DIR} — só a API está no ar.")
