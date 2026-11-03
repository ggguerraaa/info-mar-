"""
Painel do porto (o que abre ao clicar num porto no mapa) e o Resumo.

Regra do projeto: todo bloco traz a fonte e quando foi obtido; o que não tem
fonte volta None e o painel mostra "sem dado". Nada aqui inventa número.

Navios no porto: pela distância à coordenada do porto (raio, ver
RAIO_PORTO_KM), classificados pelo status de navegação que o próprio navio
transmite. "A caminho": o destino digitado pela tripulação cita o nome do
porto ou o código UN/LOCODE.
"""

from __future__ import annotations

import math
import re
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import ais_stream
from config.port_operations_config import NOS_PARA_KMH, PORT_CONFIGS, PortConfig
from praticagem import porto_tem_fonte_de_praticagem
from sea_conditions import buscar_tempo_porto
from storage import navios_com_destino, obter_ultima_barra_status, obter_ultimo_indice_por_porto
from tide_now import agora_brasilia, altura_mare_agora, curva_do_dia, eventos_formatados, fonte_da_tabua, status_mare_agora

RAIO_PORTO_KM = 20  # cobre berços e a área de fundeio próxima; aproximação declarada na tela
FONTE_TEMPO = "Open-Meteo (CC BY 4.0), previsão de modelo"

MANAUS = {"slug": "manaus", "porto": "Manaus", "estado": "AM", "lat": -3.129167, "lon": -60.021389}

# Termos que identificam o porto no destino digitado (sem acento, maiúsculas).
# UN/LOCODE só dos códigos conferidos; os demais portos casam pelo nome.
_TERMOS_DESTINO: dict[str, list[str]] = {
    "santos": ["SANTOS", "BRSSZ"],
    "paranagua": ["PARANAGUA", "BRPNG"],
    "rio_grande": ["RIO GRANDE", "BRRIG"],
    "itajai": ["ITAJAI", "BRITJ"],
    "suape": ["SUAPE", "BRSUA"],
    "vitoria": ["VITORIA", "BRVIX"],
    "itaqui": ["ITAQUI", "BRITQ"],
    "recife": ["RECIFE", "BRREC"],
    "salvador": ["SALVADOR", "BRSSA"],
    "itaguai": ["ITAGUAI", "SEPETIBA"],
    "rio_de_janeiro": ["RIO DE JANEIRO", "BRRIO"],
    "sao_sebastiao": ["SAO SEBASTIAO", "BRSSO"],
    "sao_francisco_do_sul": ["SAO FRANCISCO DO SUL", "S FRANCISCO DO SUL", "BRSFS"],
    "belem": ["BELEM", "BRBEL"],
    "vila_do_conde": ["VILA DO CONDE"],
    "fortaleza": ["FORTALEZA", "MUCURIPE", "BRFOR"],
    "manaus": ["MANAUS", "BRMAO"],
}

_PONTOS_CARDEAIS = ["N", "NE", "L", "SE", "S", "SO", "O", "NO"]


def _cardeal(graus: float | None) -> str | None:
    if graus is None:
        return None
    return _PONTOS_CARDEAIS[round(graus / 45) % 8]


def _nos(kmh: float | None) -> float | None:
    return None if kmh is None else round(kmh / NOS_PARA_KMH, 1)


def _normalizar(texto: str) -> str:
    sem_acento = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return " " + re.sub(r"[^A-Z0-9]+", " ", sem_acento.upper()).strip() + " "


def _cita_porto(destino: str, slug: str) -> bool:
    normal = _normalizar(destino)
    compacto = normal.replace(" ", "")
    for termo in _TERMOS_DESTINO.get(slug, []):
        if f" {termo} " in normal or (len(termo) == 5 and termo.startswith("BR") and termo in compacto):
            return True
    return False


def _distancia_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 6371.0 * 2 * math.asin(math.sqrt(a))


# ------------------------------------------------------------ blocos


def _bloco_mare(cfg: PortConfig) -> dict | None:
    if not cfg.dhn_id:
        return None
    altura = altura_mare_agora(cfg.dhn_id)
    if altura is None:
        return None
    status = status_mare_agora(cfg.dhn_id)
    agora = agora_brasilia().replace(tzinfo=None)
    hoje = agora.date()
    eventos = eventos_formatados(cfg.dhn_id, hoje) + eventos_formatados(cfg.dhn_id, hoje + timedelta(days=1))
    futuros = [e for e in eventos if datetime.fromisoformat(e["horario"]) > agora]
    proxima = {
        tipo: next(({"horario": e["horario"], "altura_m": e["altura_m"]} for e in futuros if e["tipo"] == tipo), None)
        for tipo in ("alta", "baixa")
    }
    return {
        "altura_m": round(altura, 2),
        "subindo": status["subindo"] if status else None,
        "proxima_alta": proxima["alta"],
        "proxima_baixa": proxima["baixa"],
        "curva_hoje": curva_do_dia(cfg.dhn_id),
        "eventos_hoje": [e for e in eventos if e["horario"].startswith(hoje.isoformat())],
        "hora_atual": agora.strftime("%H:%M"),
        "fonte": fonte_da_tabua(cfg.dhn_id),
    }


def _bloco_tempo(lat: float, lon: float, com_onda: bool = True, horas: int = 12) -> dict:
    tempo = buscar_tempo_porto(lat, lon, horas=horas)
    atual = tempo["atual"]
    return {
        "fonte": FONTE_TEMPO,
        "obtido_em": tempo["obtido_em"],
        "vento_kn": _nos(atual.get("vento_kmh")),
        "vento_direcao": _cardeal(atual.get("vento_direcao_deg")),
        "rajada_kn": _nos(atual.get("rajada_kmh")),
        # Manaus é rio: o modelo de onda oceânica não se aplica
        "onda_m": atual.get("onda_altura_m") if com_onda else None,
        "onda_periodo_s": atual.get("onda_periodo_s") if com_onda else None,
        "onda_direcao": _cardeal(atual.get("onda_direcao_deg")) if com_onda else None,
        "visibilidade_km": atual.get("visibilidade_km"),
        "proximas_horas": [
            {
                "hora": p["hora"][11:16],
                "vento_kn": _nos(p.get("vento_kmh")),
                "rajada_kn": _nos(p.get("rajada_kmh")),
                "onda_m": p.get("onda_altura_m") if com_onda else None,
            }
            for p in tempo["horas"]
        ],
    }


def _bloco_barra(cfg: PortConfig) -> dict:
    if not porto_tem_fonte_de_praticagem(cfg.porto):
        return {"disponivel": False}
    barra = obter_ultima_barra_status(cfg.porto)
    if barra is None:
        return {"disponivel": True, "situacao": None, "fonte": None, "coletado_em": None}
    return {
        "disponivel": True,
        "situacao": barra["situacao"],
        "fechada": bool(barra["fechada"]),
        "fonte": barra["fonte"],
        "desde": barra["desde"],
        "coletado_em": barra["coletado_em"],
    }


def _bloco_calado(cfg: PortConfig) -> dict | None:
    if cfg.calado_maximo_m is None:
        return None
    return {
        "calado_maximo_m": cfg.calado_maximo_m,
        "canal": cfg.canal,
        "bercos": cfg.berços or None,
        "fonte": cfg.fonte_oficial,
        "verificado_em": cfg.ultima_verificacao,
        "confianca": cfg.calado_confianca,
    }


_PARAMETROS_INDICE = {
    "mare_minima_m": "maré mínima", "mare_ideal_m": "maré ideal",
    "vento_ideal_kmh": "vento ideal", "vento_limite_kmh": "vento limite",
    "onda_ideal_m": "onda ideal", "onda_limite_m": "onda limite",
}


def _bloco_indice(cfg: PortConfig) -> dict:
    explicacao = ("Nota de 0 a 100: maré vale 50%, vento 25% e onda 25%, cada um comparado aos "
                  "limites do porto com fonte. Barra fechada pela praticagem torna a situação restrita.")
    if not cfg.indice_calculavel:
        faltam = [nome for campo, nome in _PARAMETROS_INDICE.items() if getattr(cfg, campo) is None]
        return {
            "calculavel": False, "valor": None, "status": None, "calculado_em": None,
            "explicacao": explicacao,
            "motivo": "Não calculado: falta fonte oficial para " + ", ".join(faltam) + ".",
        }
    info = obter_ultimo_indice_por_porto().get(cfg.porto)
    return {
        "calculavel": True,
        "valor": info["indice"] if info else None,
        "status": info["status"] if info else None,
        "calculado_em": info["calculado_em"] if info else None,
        "explicacao": explicacao,
        "motivo": None if info else "Ainda não calculado neste ciclo (recalcula a cada 30 min).",
    }


def _situacao(indice: dict, barra: dict) -> dict:
    if barra.get("fechada"):
        return {"palavra": "Restrita", "motivo": "Barra fechada pela praticagem"}
    if indice["status"]:
        palavra = {"ideal": "Normal", "atencao": "Atenção", "restrita": "Restrita"}[indice["status"]]
        return {"palavra": palavra, "motivo": "Índice operacional"}
    if barra.get("situacao"):
        return {"palavra": "Aberta", "motivo": "Barra aberta pela praticagem; índice sem dado"}
    return {"palavra": "Sem dado", "motivo": "Sem índice nem confirmação de barra com fonte"}


_cache_destinos: tuple[float, list[dict]] | None = None


def _destinos() -> list[dict]:
    global _cache_destinos
    if _cache_destinos is None or time.monotonic() - _cache_destinos[0] > 60:
        _cache_destinos = (time.monotonic(), navios_com_destino())
    return _cache_destinos[1]


def bloco_navios(slug: str, lat: float, lon: float) -> dict:
    agora = datetime.now(timezone.utc)
    grupos: dict[str, list] = {"atracados": [], "fundeados": [], "parados": [], "em_movimento": []}
    na_area: set[str] = set()
    for p in list(ais_stream.ultimas_posicoes.values()):
        if abs(p["latitude"] - lat) > 0.3 or abs(p["longitude"] - lon) > 0.3:
            continue  # corte barato antes da distância
        dist = _distancia_km(lat, lon, p["latitude"], p["longitude"])
        if dist > RAIO_PORTO_KM:
            continue
        na_area.add(p["mmsi"])
        status = p.get("status_navegacao")
        if status == 5:
            grupo = "atracados"
        elif status == 1:
            grupo = "fundeados"
        elif (p.get("velocidade_nos") or 0) < 0.5:
            grupo = "parados"
        else:
            grupo = "em_movimento"
        grupos[grupo].append(_resumo_navio(p, agora, distancia_km=round(dist, 1)))

    a_caminho = []
    for d in _destinos():
        if d["mmsi"] in na_area or not _cita_porto(d["destino"], slug):
            continue
        p = ais_stream.ultimas_posicoes.get(d["mmsi"])
        if p is None:
            continue  # só quem tem posição nas últimas 6 h
        item = _resumo_navio(p, agora, distancia_km=round(_distancia_km(lat, lon, p["latitude"], p["longitude"])))
        item.update(nome=d["nome_navio"] or item["nome"], destino=d["destino"], eta_informada=d["eta_informada"])
        a_caminho.append(item)

    for lista in grupos.values():
        lista.sort(key=lambda n: n["nome"] or "~")
    a_caminho.sort(key=lambda n: n["distancia_km"])
    return {
        "raio_km": RAIO_PORTO_KM,
        **{k: v[:40] for k, v in grupos.items()},
        "a_caminho": a_caminho[:40],
        "fonte": "AISstream.io (antenas terrestres); destino informado pela tripulação",
    }


def _resumo_navio(p: dict, agora: datetime, **extra) -> dict:
    return {
        "mmsi": p["mmsi"],
        "nome": p.get("nome_navio"),
        "velocidade_nos": p.get("velocidade_nos"),
        "idade_s": int((agora - datetime.fromisoformat(p["timestamp_utc"])).total_seconds()),
        **extra,
    }


# ------------------------------------------------------------ montagem


def _bloco_calado_manaus(calados) -> dict | None:
    """Calados aproximados por berço, publicados pelo Porto de Manaus junto da
    régua do rio (mudam com o nível). O maior vale como "calado máximo"."""
    dados = _tentar(calados)
    if not dados:
        return None
    maior = max(dados["bercos"], key=lambda b: b["calado_m"])
    return {
        "calado_maximo_m": maior["calado_m"],
        "canal": f"Maior calado no berço {maior['berco']}. Valores aproximados, que variam com o nível do rio.",
        "bercos": " · ".join(f"{b['berco']}: {b['calado_m']:.2f} m".replace(".", ",") for b in dados["bercos"]),
        "fonte": dados["fonte"],
        "verificado_em": dados["data_referencia"],
        "confianca": "aproximado, como publicado pelo Porto de Manaus",
    }


def painel_manaus(nivel_rio, calados) -> dict:
    tempo = _tentar(lambda: _bloco_tempo(MANAUS["lat"], MANAUS["lon"], com_onda=False))
    rio = _tentar(nivel_rio)
    return {
        **MANAUS,
        "modelo": "nivel_rio",
        "situacao": {"palavra": "Sem dado", "motivo": "Porto fluvial: sem índice operacional"},
        "indice": {"calculavel": False, "valor": None, "status": None, "calculado_em": None,
                   "explicacao": None, "motivo": "Porto fluvial: o índice de maré não se aplica."},
        "mare": None,
        "rio": rio,
        "tempo": tempo,
        "barra": {"disponivel": False},
        "calado": _bloco_calado_manaus(calados),
        "limites": [],
        "navios": bloco_navios("manaus", MANAUS["lat"], MANAUS["lon"]),
    }


def _tentar(funcao):
    """Fonte externa fora do ar vira "sem dado" no bloco, não derruba o painel."""
    try:
        return funcao()
    except Exception as exc:  # noqa: BLE001
        print(f"Painel do porto: fonte falhou: {exc}")
        return None


def painel_porto(slug: str) -> dict | None:
    cfg = PORT_CONFIGS.get(slug)
    if cfg is None:
        return None
    indice = _bloco_indice(cfg)
    barra = _bloco_barra(cfg)
    return {
        "slug": slug,
        "porto": cfg.porto,
        "estado": cfg.estado,
        "lat": cfg.lat,
        "lon": cfg.lon,
        "modelo": "mare",
        "situacao": _situacao(indice, barra),
        "indice": indice,
        "mare": _tentar(lambda: _bloco_mare(cfg)),
        "rio": None,
        "tempo": _tentar(lambda: _bloco_tempo(cfg.lat, cfg.lon)),
        "barra": barra,
        "calado": _bloco_calado(cfg),
        "limites": [
            {k: v for k, v in vars(lim).items() if v is not None}
            for lim in cfg.limites
        ],
        "navios": bloco_navios(slug, cfg.lat, cfg.lon),
    }


def _linha_resumo(slug: str, nivel_rio, calados) -> dict | None:
    if slug == "manaus":
        calado = _bloco_calado_manaus(calados)
        return {
            **MANAUS, "modelo": "nivel_rio", "calado_maximo_m": calado["calado_maximo_m"] if calado else None, "mare": None,
            "rio": _tentar(nivel_rio),
            "tempo": _tentar(lambda: _bloco_tempo(MANAUS["lat"], MANAUS["lon"], com_onda=False, horas=0)),
            "barra": {"disponivel": False},
            "indice": {"valor": None, "status": None, "calculavel": False, "calculado_em": None},
            "situacao": {"palavra": "Sem dado", "motivo": "Porto fluvial: sem índice operacional"},
        }
    cfg = PORT_CONFIGS.get(slug)
    if cfg is None:
        return None
    indice = _bloco_indice(cfg)
    barra = _bloco_barra(cfg)
    altura = altura_mare_agora(cfg.dhn_id) if cfg.dhn_id else None
    status = status_mare_agora(cfg.dhn_id) if cfg.dhn_id else None
    return {
        "slug": slug, "porto": cfg.porto, "estado": cfg.estado, "lat": cfg.lat, "lon": cfg.lon,
        "modelo": "mare",
        "calado_maximo_m": cfg.calado_maximo_m,
        "mare": None if altura is None else {
            "altura_m": round(altura, 2), "subindo": status["subindo"] if status else None,
            "fonte": fonte_da_tabua(cfg.dhn_id),
        },
        "tempo": _tentar(lambda: _bloco_tempo(cfg.lat, cfg.lon, horas=0)),
        "barra": barra,
        "indice": indice,
        "situacao": _situacao(indice, barra),
    }


def resumo_portos(slugs: list[str], nivel_rio, calados) -> list[dict]:
    """Uma linha por porto para a tela Resumo: maré agora, vento, onda,
    barra, índice — cada valor com a hora em que foi obtido. Os portos são
    consultados em paralelo (Open-Meteo frio leva ~1 s por porto)."""
    with ThreadPoolExecutor(max_workers=6) as executor:
        linhas = list(executor.map(lambda s: _linha_resumo(s, nivel_rio, calados), slugs))
    return [linha for linha in linhas if linha]


def todos_os_slugs() -> list[str]:
    return [*PORT_CONFIGS.keys(), "manaus"]
