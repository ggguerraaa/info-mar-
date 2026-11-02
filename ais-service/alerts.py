"""
Geracao de alertas operacionais por porto — porta de buildAlerts() em
lib/portOperations.ts do fork MareAgora (GPL, so a logica foi portada,
codigo escrito do zero).

Regras REAIS extraidas do fork:
  - ressaca: onda >= limite do porto -> severidade "danger"
  - chuva: probabilidade de chuva >= 70% -> "warning"
  - vento: vento >= limite do porto -> "danger"

Ressaca e vento usam o limite MAIS RESTRITIVO com fonte do porto
(config.limites). Porto sem limite com fonte não gera esses dois alertas —
não inventamos limite.
  - neblina: visibilidade < 2km -> "warning"
  - mare excepcional: coeficiente >= 100 ou <= 25 -> "warning"
"""

from dataclasses import dataclass

from config.port_operations_config import NOS_PARA_KMH, PortConfig
from sea_conditions import WeatherSnapshot


@dataclass
class Alerta:
    id: str
    icone: str
    mensagem: str
    severidade: str  # "warning" ou "danger"


def montar_alertas(
    onda_altura_m: float | None,
    weather: WeatherSnapshot,
    coeficiente_mare: float | None,
    config: PortConfig,
) -> list[Alerta]:
    alertas: list[Alerta] = []
    onda_limite_m = config.limite_mais_restritivo("onda_hs_m")
    vento_limite_kn = config.limite_mais_restritivo("vento_kn")
    vento_limite_kmh = vento_limite_kn * NOS_PARA_KMH if vento_limite_kn is not None else None

    if onda_altura_m is not None and onda_limite_m is not None and onda_altura_m >= onda_limite_m:
        alertas.append(Alerta(
            id="ressaca",
            icone="⚠️",
            mensagem=f"Ressaca — ondas de {onda_altura_m:.1f}m acima do limite operacional em {config.porto}",
            severidade="danger",
        ))

    if weather.probabilidade_chuva_pct is not None and weather.probabilidade_chuva_pct >= 70:
        alertas.append(Alerta(
            id="chuva",
            icone="⚠️",
            mensagem=f"Chuva intensa prevista ({weather.probabilidade_chuva_pct}% de probabilidade) em {config.porto}",
            severidade="warning",
        ))

    if weather.vento_kmh is not None and vento_limite_kmh is not None and weather.vento_kmh >= vento_limite_kmh:
        alertas.append(Alerta(
            id="vento",
            icone="⚠️",
            mensagem=f"Vento de {round(weather.vento_kmh)} km/h acima do limite operacional em {config.porto}",
            severidade="danger",
        ))

    if weather.visibilidade_km is not None and weather.visibilidade_km < 2:
        alertas.append(Alerta(
            id="neblina",
            icone="⚠️",
            mensagem=f"Neblina — visibilidade reduzida a {weather.visibilidade_km:.1f}km em {config.porto}",
            severidade="warning",
        ))

    if coeficiente_mare is not None and (coeficiente_mare >= 100 or coeficiente_mare <= 25):
        alertas.append(Alerta(
            id="mare-excepcional",
            icone="⚠️",
            mensagem=f"Maré excepcional — coeficiente {coeficiente_mare} em {config.porto}",
            severidade="warning",
        ))

    return alertas
