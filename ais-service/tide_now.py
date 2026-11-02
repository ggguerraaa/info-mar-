"""
Altura de mare no minuto atual — interpolacao cossenoidal entre os dois
eventos mais proximos (atravessando a meia-noite), REPLICANDO tideAtMinute() de
lib/tideUtils.ts do fork MareAgora (GPL, so a logica foi portada).

Le a tabua anual em data/mare/{dhn_id}.json (DHN oficial ou previsao harmonica,
ver tools/gerar_tabua_harmonica.py).
"""

import json
import math
import pathlib
from datetime import date, datetime, timedelta, timezone

DATA_DIR = pathlib.Path(__file__).parent / "data" / "mare"

# Os eventos da DHN vêm em hora LOCAL (UTC-3, sem horário de verão desde
# 2019) — "agora" e "hoje" precisam estar no mesmo fuso, senão a maré
# atual sai deslocada 3h (e "hoje" vira amanhã a partir das 21h).
FUSO_BRASILIA = timezone(timedelta(hours=-3))


def agora_brasilia() -> datetime:
    return datetime.now(FUSO_BRASILIA)


def hoje_brasilia() -> date:
    return agora_brasilia().date()


def _carregar_eventos(dhn_id: str) -> list[dict]:
    caminho = DATA_DIR / f"{dhn_id}.json"
    if not caminho.exists():
        return []
    dados = json.loads(caminho.read_text(encoding="utf-8"))
    return sorted(dados.get("events", []), key=lambda e: e["dt"])


def fonte_da_tabua(dhn_id: str, dia: date | None = None) -> str | None:
    """Origem da tábua usada no dia: a DHN oficial ou a previsão harmônica
    gerada por tools/gerar_tabua_harmonica.py (marcada por evento)."""
    dia_str = (dia or hoje_brasilia()).isoformat()
    eventos = [e for e in _carregar_eventos(dhn_id) if e["dt"].startswith(dia_str)]
    if not eventos:
        return None
    if any(e.get("origem") == "harmonica" for e in eventos):
        return "Previsão astronômica calculada a partir da tábua DHN (análise harmônica)"
    return "Tábua de marés DHN/Marinha do Brasil (previsão astronômica)"


def _eventos_de_hoje(dhn_id: str, hoje: date | None = None) -> list[dict]:
    hoje_str = (hoje or hoje_brasilia()).isoformat()
    return [e for e in _carregar_eventos(dhn_id) if e["dt"].startswith(hoje_str)]


def _instante_local(agora: datetime) -> datetime:
    """Converte pra hora de Brasília sem tzinfo — mesmo formato do "dt" da DHN."""
    if agora.tzinfo is not None:
        agora = agora.astimezone(FUSO_BRASILIA)
    return agora.replace(tzinfo=None)


def _interpolar(eventos: list[dict], instante: datetime) -> float | None:
    """Interpolação entre o evento anterior e o seguinte ao instante,
    usando data+hora completas — atravessa a meia-noite (o último evento de
    hoje se liga ao primeiro de amanhã), em vez de cair no 1º evento do dia."""
    anterior = None
    for evento in eventos:
        dt = datetime.fromisoformat(evento["dt"])
        if dt >= instante:
            if anterior is None:
                return evento["height_m"]
            dt_ant, h_ant = anterior
            ratio = (instante - dt_ant) / (dt - dt_ant) if dt != dt_ant else 0
            # Interpolação cossenoidal: entre uma preamar e uma baixamar a maré
            # varia devagar perto dos extremos e rápido no meio (regra dos
            # doze avos) — a linear desenhava "dente de serra" no gráfico.
            return h_ant + (evento["height_m"] - h_ant) * (1 - math.cos(math.pi * ratio)) / 2
        anterior = (dt, evento["height_m"])
    return anterior[1] if anterior else None


def altura_mare_agora(dhn_id: str, agora: datetime | None = None) -> float | None:
    """Retorna a altura de maré interpolada para o instante `agora`
    (UTC-3 / horário de Brasília, mesma referência da DHN), ou None se
    não houver dados de hoje ainda baixados.
    """
    instante = _instante_local(agora or agora_brasilia())
    eventos = _carregar_eventos(dhn_id)
    if not any(e["dt"].startswith(instante.date().isoformat()) for e in eventos):
        return None
    return _interpolar(eventos, instante)


def status_mare_agora(dhn_id: str, agora: datetime | None = None) -> dict | None:
    """Status atual da maré (subindo/descendo) + próximo evento — porta de
    getTideStatus() em lib/tideUtils.ts do fork MareAgora (GPL, só a
    lógica foi portada). Retorna None se não houver eventos de hoje."""
    instante = _instante_local(agora or agora_brasilia())
    eventos = _carregar_eventos(dhn_id)
    if not any(e["dt"].startswith(instante.date().isoformat()) for e in eventos):
        return None

    anterior = None
    proximo = None
    for evento in eventos:
        if datetime.fromisoformat(evento["dt"]) > instante:
            proximo = evento
            break
        anterior = evento

    if proximo is None:
        return None  # fim da tábua baixada (ex.: virada de ano sem a nova)

    altura_anterior = anterior["height_m"] if anterior else 0
    return {
        "subindo": proximo["height_m"] > altura_anterior,
        "proximo_evento": {
            "horario": proximo["dt"],
            "altura_m": proximo["height_m"],
        },
    }


def curva_do_dia(dhn_id: str, hoje: date | None = None, passo_minutos: int = 30) -> list[dict]:
    """Gera a curva de maré do dia inteiro (interpolada a cada `passo_minutos`)
    — usado pelo mini-gráfico do painel (TideChart). Reaproveita a mesma
    interpolação de altura_mare_agora, só que varrendo o dia todo."""
    hoje = hoje or hoje_brasilia()
    eventos = _carregar_eventos(dhn_id)
    if not any(e["dt"].startswith(hoje.isoformat()) for e in eventos):
        return []

    inicio = datetime(hoje.year, hoje.month, hoje.day)
    pontos = []
    for minuto in range(0, 1440, passo_minutos):
        altura = _interpolar(eventos, inicio + timedelta(minutes=minuto))
        pontos.append({"hora": f"{minuto // 60:02d}:{minuto % 60:02d}", "altura_m": round(altura, 2)})
    return pontos


def eventos_formatados(dhn_id: str, dia: date) -> list[dict]:
    """Eventos de um dia (ex: ontem) já classificados como alta/baixa —
    infere alta/baixa comparando com os vizinhos
    (comparação com vizinhos), usada aqui pro card de Histórico."""
    eventos = sorted(_eventos_de_hoje(dhn_id, dia), key=lambda e: e["dt"])
    resultado = []
    for i, evento in enumerate(eventos):
        atual = evento["height_m"]
        anterior = eventos[i - 1]["height_m"] if i > 0 else None
        seguinte = eventos[i + 1]["height_m"] if i < len(eventos) - 1 else None
        vizinhos = [v for v in (anterior, seguinte) if v is not None]

        if vizinhos and all(atual >= v for v in vizinhos):
            tipo = "alta"
        elif vizinhos and all(atual <= v for v in vizinhos):
            tipo = "baixa"
        else:
            tipo = "—"

        resultado.append({"tipo": tipo, "horario": evento["dt"], "altura_m": atual})
    return resultado
