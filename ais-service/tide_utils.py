"""
Coeficiente de mare e deteccao de sizigia/quadratura.

Porta em Python da LOGICA de 'lib/tideUtils.ts' e 'lib/mareCiclo.ts' do
MareAgora (GPL) — reescrita do zero, so o metodo foi reaproveitado.

Regra descrita na analise recebida:
  - Se houver eventos reais do dia (preamar/baixamar da DHN), o coeficiente
    usa a amplitude real: coef = amplitude_range * 55
  - Senao, cai para uma formula astronomica baseada na idade da lua
    (TODO: obter a formula exata usada no original antes de confiar nela
    em producao — aqui vai um placeholder simples a refinar)
"""

from dataclasses import dataclass


@dataclass
class EventoMare:
    tipo: str  # "preamar" ou "baixamar"
    altura_m: float


def coeficiente_por_amplitude_real(eventos_do_dia: list[EventoMare]) -> float | None:
    """Calcula o coeficiente de mare a partir de eventos reais do dia.

    Retorna None se nao houver eventos suficientes (fallback para
    coeficiente_por_fase_lunar).
    """
    if len(eventos_do_dia) < 2:
        return None
    alturas = [e.altura_m for e in eventos_do_dia]
    amplitude = max(alturas) - min(alturas)
    return max(5, min(120, round(amplitude * 55)))


def idade_da_lua(agora=None) -> float:
    """Formula REAL extraida de lib/tideUtils.ts (getMoonAge) do fork
    MareAgora (GPL, so a logica foi portada). Referencia: Lua Nova em
    2000-01-06 18:14 UTC.
    """
    from datetime import datetime, timezone

    agora = agora or datetime.now(timezone.utc)
    LUNAR_MONTH = 29.530588853
    referencia = datetime(2000, 1, 6, 18, 14, tzinfo=timezone.utc)
    diff_dias = (agora - referencia).total_seconds() / 86400
    idade = diff_dias % LUNAR_MONTH
    return idade + LUNAR_MONTH if idade < 0 else idade


def coeficiente_por_fase_lunar(idade_lua_dias: float) -> int:
    """Formula REAL extraida de lib/tideUtils.ts (getTideCoefficient) do
    fork MareAgora (GPL, so a logica foi portada, codigo escrito do zero).

    value = round(70 + cos(angle) * 50)
    angle = (idade / 29.530588853) * 2*pi * 2
    Resultado tipicamente entre 20 e 120.
    """
    import math

    LUNAR_MONTH = 29.530588853
    angle = (idade_lua_dias / LUNAR_MONTH) * 2 * math.pi * 2
    valor = round(70 + math.cos(angle) * 50)
    return max(5, min(120, valor))


def classificar_coeficiente(coef: float) -> str:
    """Limiares reais do fork (getTideCoefficient): <=40 maré morta
    (quadratura), >=90 maré viva (sizígia), >70 moderada alta, senão moderada."""
    if coef <= 40:
        return "quadratura"
    if coef >= 90:
        return "sizigia"
    if coef > 70:
        return "moderada_alta"
    return "moderada"


MOON_PHASE_NAMES_PT = {
    "new": "Lua Nova", "waxing_crescent": "Lua Crescente", "first_quarter": "Quarto Crescente",
    "waxing_gibbous": "Gibosa Crescente", "full": "Lua Cheia", "waning_gibbous": "Gibosa Minguante",
    "last_quarter": "Quarto Minguante", "waning_crescent": "Lua Minguante",
}


def fase_da_lua(idade_dias: float) -> dict:
    """Formula REAL extraida de lib/tideUtils.ts (getMoonPhase) do fork
    MareAgora (GPL, so a logica foi portada)."""
    faixas = [
        (1.84566, "new", "🌑"), (5.53699, "waxing_crescent", "🌒"),
        (9.22831, "first_quarter", "🌓"), (12.91963, "waxing_gibbous", "🌔"),
        (16.61096, "full", "🌕"), (20.30228, "waning_gibbous", "🌖"),
        (23.99361, "last_quarter", "🌗"), (27.68493, "waning_crescent", "🌘"),
    ]
    for limite, chave, icone in faixas:
        if idade_dias < limite:
            return {"nome": MOON_PHASE_NAMES_PT[chave], "icone": icone}
    return {"nome": MOON_PHASE_NAMES_PT["new"], "icone": "🌑"}
