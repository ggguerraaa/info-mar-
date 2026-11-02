"""
Próximos picos de sizígia (maré viva) e quadratura (maré morta) —
porta de lib/mareCiclo.ts do fork MareAgora (GPL, só a lógica foi
portada, código escrito do zero).

Varre os próximos N dias calculando o coeficiente por fase lunar (sem
depender de eventos reais do dia, já que é uma projeção futura) e acha
os picos locais (máximo para sizígia, mínimo para quadratura).
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from tide_utils import coeficiente_por_fase_lunar, idade_da_lua


@dataclass
class PicoMare:
    data: date
    coeficiente: float


def proximos_picos(tipo: str, dias: int = 90) -> list[PicoMare]:
    """tipo: 'viva' (sizígia, coef >= 85) ou 'morta' (quadratura, coef <= 45)."""
    hoje = datetime.now(timezone.utc).replace(hour=12, minute=0, second=0, microsecond=0)

    valores: list[tuple[date, float]] = []
    for i in range(dias):
        d = hoje + timedelta(days=i)
        coef = coeficiente_por_fase_lunar(idade_da_lua(d))
        valores.append((d.date(), coef))

    picos: list[PicoMare] = []
    for i in range(1, len(valores) - 1):
        data_i, coef_i = valores[i]
        _, coef_anterior = valores[i - 1]
        _, coef_seguinte = valores[i + 1]

        if tipo == "viva" and coef_i >= coef_anterior and coef_i >= coef_seguinte and coef_i >= 85:
            picos.append(PicoMare(data=data_i, coeficiente=coef_i))
        if tipo == "morta" and coef_i <= coef_anterior and coef_i <= coef_seguinte and coef_i <= 45:
            picos.append(PicoMare(data=data_i, coeficiente=coef_i))

    return picos
