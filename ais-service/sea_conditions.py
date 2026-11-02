"""
Busca de condicoes do mar/tempo via Open-Meteo — URLs REAIS extraidas de
hooks/usePortOperationsData.ts do fork MareAgora (GPL, so a logica foi
portada, codigo escrito do zero). Essa e a chamada especifica usada pela
pagina de Operacoes Portuarias (mais completa que a de lib/seaConditions.ts,
que e usada em outras paginas do fork).
"""

import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

import requests

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
MARINE_URL = "https://marine-api.open-meteo.com/v1/marine"

# Cada página de porto dispara ~8 chamadas simultâneas ao Open-Meteo (e o
# scheduler mais 32 a cada ciclo) — sem cache, parte delas estoura timeout
# e o card aparece vazio ("—"). Previsão muda de hora em hora, então 10 min
# de cache não perde nada e corta quase todas as chamadas repetidas.
CACHE_TTL_S = 600
TENTATIVAS = 2
TIMEOUT_S = 15
_cache: dict[tuple, tuple[float, dict]] = {}
_cache_lock = threading.Lock()


def _get_json(url: str, params: dict) -> dict:
    chave = (url, tuple(sorted(params.items())))
    with _cache_lock:
        item = _cache.get(chave)
        if item and item[0] > time.monotonic():
            return item[1]

    ultimo_erro: Exception | None = None
    for tentativa in range(TENTATIVAS):
        try:
            resp = requests.get(url, params=params, timeout=TIMEOUT_S)
            resp.raise_for_status()
            dados = resp.json()
            # hora real da consulta — o painel mostra "atualizado há X" mesmo vindo do cache
            dados["_obtido_em"] = datetime.now(timezone.utc).isoformat()
            with _cache_lock:
                _cache[chave] = (time.monotonic() + CACHE_TTL_S, dados)
            return dados
        except Exception as exc:  # noqa: BLE001
            ultimo_erro = exc
            if tentativa < TENTATIVAS - 1:
                time.sleep(1)
    assert ultimo_erro is not None
    raise ultimo_erro


@dataclass
class WeatherSnapshot:
    temperatura_c: float | None = None
    vento_kmh: float | None = None
    vento_direcao_deg: float | None = None
    probabilidade_chuva_pct: float | None = None
    umidade_pct: float | None = None
    pressao_hpa: float | None = None
    visibilidade_km: float | None = None


@dataclass
class CondicoesOperacionais:
    onda_altura_m: float | None
    weather: WeatherSnapshot
    onda_periodo_s: float | None = None
    onda_direcao_deg: float | None = None
    # próximas 24h a partir da hora atual: [{"hora", "onda_altura_m", "onda_periodo_s"}]
    onda_proximas_24h: list[dict] = field(default_factory=list)
    obtido_em: str | None = None  # hora da consulta ao Open-Meteo (mais antiga das duas)


def _hora_atual_str(tz_offset_str: str = "America/Sao_Paulo") -> str:
    # Open-Meteo retorna "time" no fuso pedido (timezone=...) — aqui
    # aproximamos comparando por UTC-3 (Brasil), suficiente para achar a
    # hora mais próxima no array horário.
    from datetime import timedelta

    agora_brasilia = datetime.now(timezone.utc) - timedelta(hours=3)
    return agora_brasilia.strftime("%Y-%m-%dT%H:00")


def buscar_condicoes_operacionais(lat: float, lon: float) -> CondicoesOperacionais:
    weather_params = {
        "latitude": lat,
        "longitude": lon,
        "current": "temperature_2m,relative_humidity_2m,surface_pressure,"
        "wind_speed_10m,wind_direction_10m,precipitation_probability,visibility",
        "wind_speed_unit": "kmh",
        "forecast_days": 4,
        "timezone": "America/Sao_Paulo",
    }
    marine_params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": "wave_height,wave_period,wave_direction",
        "forecast_days": 4,
        "timezone": "America/Sao_Paulo",
    }

    weather = WeatherSnapshot()
    onda_altura_m: float | None = None
    onda_periodo_s: float | None = None
    onda_direcao_deg: float | None = None
    onda_24h: list[dict] = []

    obtido_em: list[str] = []
    try:
        resposta = _get_json(FORECAST_URL, weather_params)
        obtido_em.append(resposta["_obtido_em"])
        current = resposta.get("current", {})
        weather = WeatherSnapshot(
            temperatura_c=current.get("temperature_2m"),
            vento_kmh=current.get("wind_speed_10m"),
            vento_direcao_deg=current.get("wind_direction_10m"),
            probabilidade_chuva_pct=current.get("precipitation_probability"),
            umidade_pct=current.get("relative_humidity_2m"),
            pressao_hpa=current.get("surface_pressure"),
            visibilidade_km=(current["visibility"] / 1000) if current.get("visibility") is not None else None,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"Falha ao buscar weather (Open-Meteo Forecast): {exc}")

    try:
        resposta = _get_json(MARINE_URL, marine_params)
        obtido_em.append(resposta["_obtido_em"])
        dados = resposta.get("hourly", {})
        horas = dados.get("time", [])
        alturas = dados.get("wave_height", [])
        periodos = dados.get("wave_period", [None] * len(horas))
        direcoes = dados.get("wave_direction", [None] * len(horas))
        hora_alvo = _hora_atual_str()
        i = horas.index(hora_alvo) if hora_alvo in horas else 0
        if alturas:
            onda_altura_m, onda_periodo_s, onda_direcao_deg = alturas[i], periodos[i], direcoes[i]
            onda_24h = [
                {"hora": horas[j], "onda_altura_m": alturas[j], "onda_periodo_s": periodos[j]}
                for j in range(i, min(i + 25, len(horas)))
            ]
    except Exception as exc:  # noqa: BLE001
        print(f"Falha ao buscar onda (Open-Meteo Marine): {exc}")

    return CondicoesOperacionais(
        onda_altura_m=onda_altura_m, weather=weather, onda_periodo_s=onda_periodo_s,
        onda_direcao_deg=onda_direcao_deg, onda_proximas_24h=onda_24h,
        obtido_em=min(obtido_em) if obtido_em else None,
    )


def buscar_previsao_diaria(lat: float, lon: float, dias: int = 4) -> list[dict]:
    """Previsão diária de vento máximo e onda máxima — usado pelo resumo
    de 'Próximos dias'. Não existe função equivalente isolada no fork
    (ele deriva isso da série horária completa) — aqui simplificamos
    usando os agregados diários que a própria Open-Meteo já calcula."""
    weather_params = {
        "latitude": lat, "longitude": lon,
        "daily": "wind_speed_10m_max",
        "wind_speed_unit": "kmh", "forecast_days": dias, "timezone": "America/Sao_Paulo",
    }
    marine_params = {
        "latitude": lat, "longitude": lon,
        "daily": "wave_height_max",
        "forecast_days": dias, "timezone": "America/Sao_Paulo",
    }

    dias_resultado: dict[str, dict] = {}

    try:
        daily = _get_json(FORECAST_URL, weather_params).get("daily", {})
        for data, vento in zip(daily.get("time", []), daily.get("wind_speed_10m_max", [])):
            dias_resultado.setdefault(data, {})["vento_max_kmh"] = vento
    except Exception as exc:  # noqa: BLE001
        print(f"Falha ao buscar previsão diária de vento: {exc}")

    try:
        daily = _get_json(MARINE_URL, marine_params).get("daily", {})
        for data, onda in zip(daily.get("time", []), daily.get("wave_height_max", [])):
            dias_resultado.setdefault(data, {})["onda_max_m"] = onda
    except Exception as exc:  # noqa: BLE001
        print(f"Falha ao buscar previsão diária de onda: {exc}")

    return [
        {"data": data, "vento_max_kmh": v.get("vento_max_kmh"), "onda_max_m": v.get("onda_max_m")}
        for data, v in sorted(dias_resultado.items())
    ]


def buscar_serie_horaria(lat: float, lon: float, dias: int = 5) -> list[dict]:
    """Série horária de vento/rajada/onda/período — o que faltava pra
    montar os gráficos de 'previsão detalhada' que o MaréAgora tem e a
    gente não tinha ainda. Usa os MESMOS parâmetros hourly que o fork
    usa (wind_speed_10m, wind_gusts_10m, wave_height, wave_period)."""
    weather_params = {
        "latitude": lat, "longitude": lon,
        "hourly": "wind_speed_10m,wind_gusts_10m",
        "wind_speed_unit": "kmh", "forecast_days": dias, "timezone": "America/Sao_Paulo",
    }
    marine_params = {
        "latitude": lat, "longitude": lon,
        "hourly": "wave_height,wave_period",
        "forecast_days": dias, "timezone": "America/Sao_Paulo",
    }

    pontos: dict[str, dict] = {}

    try:
        hourly = _get_json(FORECAST_URL, weather_params).get("hourly", {})
        for hora, vento, rajada in zip(
            hourly.get("time", []), hourly.get("wind_speed_10m", []), hourly.get("wind_gusts_10m", [])
        ):
            pontos.setdefault(hora, {})["vento_kmh"] = vento
            pontos.setdefault(hora, {})["rajada_kmh"] = rajada
    except Exception as exc:  # noqa: BLE001
        print(f"Falha ao buscar série horária de vento: {exc}")

    try:
        hourly = _get_json(MARINE_URL, marine_params).get("hourly", {})
        for hora, altura, periodo in zip(
            hourly.get("time", []), hourly.get("wave_height", []), hourly.get("wave_period", [])
        ):
            pontos.setdefault(hora, {})["onda_altura_m"] = altura
            pontos.setdefault(hora, {})["onda_periodo_s"] = periodo
    except Exception as exc:  # noqa: BLE001
        print(f"Falha ao buscar série horária de onda: {exc}")

    return [
        {
            "hora": hora,
            "vento_kmh": v.get("vento_kmh"),
            "rajada_kmh": v.get("rajada_kmh"),
            "onda_altura_m": v.get("onda_altura_m"),
            "onda_periodo_s": v.get("onda_periodo_s"),
        }
        for hora, v in sorted(pontos.items())
    ]


def buscar_tempo_porto(lat: float, lon: float, horas: int = 12) -> dict:
    """Vento e onda agora e nas próximas horas para o painel do porto e o
    Resumo, em DUAS chamadas por porto (previsão + marinha) — com 17 portos
    o plano gratuito (< 10.000 chamadas/dia) aguenta o cache de 10 min.
    Vento em km/h (unidade dos limites e do índice); o painel converte."""
    resultado: dict = {"obtido_em": None, "atual": {}, "horas": []}
    obtido_em: list[str] = []
    pontos: dict[str, dict] = {}
    hora_alvo = _hora_atual_str()

    try:
        resposta = _get_json(FORECAST_URL, {
            "latitude": lat, "longitude": lon,
            "current": "wind_speed_10m,wind_direction_10m,wind_gusts_10m,visibility",
            "hourly": "wind_speed_10m,wind_gusts_10m",
            "wind_speed_unit": "kmh", "forecast_days": 2, "timezone": "America/Sao_Paulo",
        })
        obtido_em.append(resposta["_obtido_em"])
        atual = resposta.get("current", {})
        resultado["atual"].update(
            vento_kmh=atual.get("wind_speed_10m"), vento_direcao_deg=atual.get("wind_direction_10m"),
            rajada_kmh=atual.get("wind_gusts_10m"),
            visibilidade_km=(atual["visibility"] / 1000) if atual.get("visibility") is not None else None,
        )
        hourly = resposta.get("hourly", {})
        for hora, vento, rajada in zip(hourly.get("time", []), hourly.get("wind_speed_10m", []),
                                       hourly.get("wind_gusts_10m", [])):
            pontos.setdefault(hora, {}).update(vento_kmh=vento, rajada_kmh=rajada)
    except Exception as exc:  # noqa: BLE001
        print(f"Falha ao buscar vento (Open-Meteo Forecast): {exc}")

    try:
        resposta = _get_json(MARINE_URL, {
            "latitude": lat, "longitude": lon,
            "hourly": "wave_height,wave_period,wave_direction",
            "forecast_days": 2, "timezone": "America/Sao_Paulo",
        })
        obtido_em.append(resposta["_obtido_em"])
        hourly = resposta.get("hourly", {})
        for hora, altura, periodo, direcao in zip(
            hourly.get("time", []), hourly.get("wave_height", []),
            hourly.get("wave_period", []), hourly.get("wave_direction", []),
        ):
            pontos.setdefault(hora, {}).update(onda_altura_m=altura, onda_periodo_s=periodo, onda_direcao_deg=direcao)
        agora = pontos.get(hora_alvo, {})
        resultado["atual"].update(
            onda_altura_m=agora.get("onda_altura_m"), onda_periodo_s=agora.get("onda_periodo_s"),
            onda_direcao_deg=agora.get("onda_direcao_deg"),
        )
    except Exception as exc:  # noqa: BLE001
        print(f"Falha ao buscar onda (Open-Meteo Marine): {exc}")

    resultado["horas"] = [{"hora": h, **v} for h, v in sorted(pontos.items()) if h >= hora_alvo][: horas + 1]
    resultado["obtido_em"] = min(obtido_em) if obtido_em else None
    return resultado
