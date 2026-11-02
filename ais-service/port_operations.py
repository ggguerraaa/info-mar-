"""
Indice operacional por porto — formula REAL extraida de
lib/portOperations.ts do fork MareAgora (GPL, so a logica foi portada).

Pesos confirmados: mare 0.5, vento 0.25, onda 0.25.

IMPORTANTE (bug corrigido nesta versao): o vento e AVALIADO EM KM/H,
nao em nos — bate com o que a Open-Meteo Marine retorna nativamente,
entao nao precisa converter nada na hora de alimentar esta funcao.
"""

from dataclasses import dataclass

from config.port_operations_config import PortConfig


@dataclass
class CondicoesAtuais:
    mare_altura_m: float
    vento_kmh: float | None
    onda_altura_m: float | None


def _score_mare(mare_altura_m: float, config: PortConfig) -> float:
    margem = mare_altura_m - config.mare_minima_m
    if margem <= 0:
        return 0.0
    denom = (config.mare_ideal_m - config.mare_minima_m) or 1
    clamped = min(margem / denom, 1.2)
    return max(0.0, min(100.0, clamped * 100))


def _score_vento(vento_kmh: float | None, config: PortConfig) -> float:
    if vento_kmh is None:
        return 70.0  # sem dado: neutro (mesma regra do fork)
    if vento_kmh <= config.vento_ideal_kmh:
        return 100.0
    if vento_kmh >= config.vento_limite_kmh:
        return 0.0
    ratio = (config.vento_limite_kmh - vento_kmh) / (config.vento_limite_kmh - config.vento_ideal_kmh)
    return max(0.0, min(100.0, ratio * 100))


def _score_onda(onda_altura_m: float | None, config: PortConfig) -> float:
    if onda_altura_m is None:
        return 70.0
    if onda_altura_m <= config.onda_ideal_m:
        return 100.0
    if onda_altura_m >= config.onda_limite_m:
        return 0.0
    ratio = (config.onda_limite_m - onda_altura_m) / (config.onda_limite_m - config.onda_ideal_m)
    return max(0.0, min(100.0, ratio * 100))


def computar_indice_operacional(condicoes: CondicoesAtuais, config: PortConfig) -> int:
    score_mare = _score_mare(condicoes.mare_altura_m, config)
    score_vento = _score_vento(condicoes.vento_kmh, config)
    score_onda = _score_onda(condicoes.onda_altura_m, config)
    ponderado = score_mare * 0.5 + score_vento * 0.25 + score_onda * 0.25
    return round(max(0.0, min(100.0, ponderado)))


def classificar_status(indice: int) -> str:
    if indice >= 70:
        return "ideal"
    if indice >= 40:
        return "atencao"
    return "restrita"


def classificar_status_com_override_barra(indice: int, barra_fechada: bool | None) -> str:
    """Mesma classificação de sempre, mas com override: se a praticagem
    confirma barra fechada/impraticável, o status vira 'restrita' na
    marra, mesmo que maré/vento/onda calculassem um índice melhor — a
    autoridade local tem prioridade sobre o nosso cálculo estimado."""
    if barra_fechada:
        return "restrita"
    return classificar_status(indice)


def classificar_indice_5_faixas(indice: int) -> dict:
    """Gauge de 5 faixas (crítica/ruim/regular/boa/excelente) — porta de
    classifyOperationalIndex() em lib/portOperations.ts do fork."""
    if indice >= 90:
        return {"label": "Excelente", "cor": "#10b981"}
    if indice >= 70:
        return {"label": "Muito Boa", "cor": "#38bdf8"}
    if indice >= 50:
        return {"label": "Regular", "cor": "#f59e0b"}
    if indice >= 30:
        return {"label": "Ruim", "cor": "#f97316"}
    return {"label": "Crítica", "cor": "#ef4444"}


def construir_pontos_operacionais(
    curva_mare: list[dict], config: PortConfig, vento_kmh: float | None, onda_altura_m: float | None
) -> list[dict]:
    """Varre o dia (pontos da curva de maré, a cada 30min) calculando o
    índice operacional em cada instante — porta de buildOperationalPoints()
    em lib/portOperations.ts. Usa vento/onda ATUAIS para todo o dia (o fork
    usa previsão hora a hora; aqui é uma simplificação — refinar quando
    tivermos a série horária completa de vento/onda)."""
    pontos = []
    for ponto in curva_mare:
        condicoes = CondicoesAtuais(
            mare_altura_m=ponto["altura_m"], vento_kmh=vento_kmh, onda_altura_m=onda_altura_m
        )
        indice = computar_indice_operacional(condicoes, config)
        pontos.append({
            "hora": ponto["hora"],
            "mare_altura_m": ponto["altura_m"],
            "indice": indice,
            "status": classificar_status(indice),
        })
    return pontos


def resumir_janela_operacional(pontos: list[dict], hora_atual_str: str) -> dict:
    """Agrupa pontos consecutivos de mesmo status em janelas e resume a
    janela atual + próxima janela ideal — porta de
    summarizeOperationalWindow() em lib/portOperations.ts."""
    if not pontos:
        return {
            "status_atual": "restrita", "janela_atual": None, "proxima_janela_ideal": None,
            "melhor_entrada": None, "melhor_saida": None, "duracao_minutos": None,
            "minutos_restantes": None, "progresso_pct": None,
        }

    def para_minuto(hora_str: str) -> int:
        h, m = hora_str.split(":")
        return int(h) * 60 + int(m)

    minuto_atual = para_minuto(hora_atual_str)

    # agrupa em janelas (blocos consecutivos do mesmo status)
    janelas = []
    inicio = pontos[0]
    anterior = pontos[0]
    for i in range(1, len(pontos) + 1):
        p = pontos[i] if i < len(pontos) else None
        if p is None or p["status"] != anterior["status"]:
            janelas.append({
                "status": anterior["status"],
                "inicio_minuto": para_minuto(inicio["hora"]),
                "fim_minuto": para_minuto(anterior["hora"]) + 30,
                "inicio_hora": inicio["hora"],
                "fim_hora": anterior["hora"],
            })
            inicio = p
        if p is not None:
            anterior = p

    # ponto mais próximo do minuto atual, pra achar o status "agora"
    mais_proximo = min(pontos, key=lambda p: abs(para_minuto(p["hora"]) - minuto_atual))
    status_atual = mais_proximo["status"]

    janela_atual = next(
        (j for j in janelas if j["inicio_minuto"] <= minuto_atual < j["fim_minuto"]), None
    )

    janelas_ideais = [j for j in janelas if j["status"] == "ideal"]
    proxima_ideal = next(
        (j for j in janelas_ideais if j["fim_minuto"] > minuto_atual),
        janelas_ideais[0] if janelas_ideais else None,
    )

    duracao = (janela_atual["fim_minuto"] - janela_atual["inicio_minuto"]) if janela_atual else None
    restante = max(0, janela_atual["fim_minuto"] - minuto_atual) if janela_atual else None
    progresso = (
        round(((minuto_atual - janela_atual["inicio_minuto"]) / duracao) * 100)
        if janela_atual and duracao else None
    )

    return {
        "status_atual": status_atual,
        "janela_atual": janela_atual,
        "proxima_janela_ideal": proxima_ideal,
        "melhor_entrada": proxima_ideal["inicio_hora"] if proxima_ideal else None,
        "melhor_saida": proxima_ideal["fim_hora"] if proxima_ideal else None,
        "duracao_minutos": duracao,
        "minutos_restantes": restante,
        "progresso_pct": progresso,
    }
