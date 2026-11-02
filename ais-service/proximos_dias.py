"""
Resumo dos "Próximos dias" (Hoje, Amanhã, Dia +2, Dia +3...) — não existe
como módulo isolado no fork (a lógica está espalhada em vários lugares),
esta é uma composição própria usando as peças já portadas:
tide_now.curva_do_dia (maré real, funciona pra qualquer data do ano já
baixado), port_operations (índice + janela), sea_conditions (previsão
diária de vento/onda).

Aproximação assumida: o índice do dia usa a maré média do dia (entre
maior e menor) — não a curva minuto a minuto — junto com o vento/onda
máximos previstos. É uma simplificação deliberada (documentada) até
termos série horária completa de vento/onda armazenada para o dia
inteiro, não só o valor "agora".
"""

from dataclasses import dataclass
from datetime import timedelta

from config.port_operations_config import PortConfig
from port_operations import (
    CondicoesAtuais,
    classificar_status,
    computar_indice_operacional,
    construir_pontos_operacionais,
    resumir_janela_operacional,
)
from tide_now import curva_do_dia, hoje_brasilia


@dataclass
class ResumoDia:
    data: str
    label: str
    maior_mare_m: float | None
    menor_mare_m: float | None
    indice: int | None
    status: str | None
    janela_a_partir: str | None


def _label_do_dia(offset: int) -> str:
    if offset == 0:
        return "Hoje"
    if offset == 1:
        return "Amanhã"
    return f"Dia +{offset}"


def resumo_proximos_dias(
    cfg: PortConfig, previsao_diaria: list[dict], dias: int = 4
) -> list[ResumoDia]:
    if not cfg.dhn_id:
        return []

    previsao_por_data = {p["data"]: p for p in previsao_diaria}
    resultado = []

    for offset in range(dias):
        dia = hoje_brasilia() + timedelta(days=offset)
        curva = curva_do_dia(cfg.dhn_id, hoje=dia)
        if not curva:
            resultado.append(ResumoDia(
                data=dia.isoformat(), label=_label_do_dia(offset),
                maior_mare_m=None, menor_mare_m=None, indice=None, status=None, janela_a_partir=None,
            ))
            continue

        alturas = [p["altura_m"] for p in curva]
        maior, menor = max(alturas), min(alturas)

        previsao = previsao_por_data.get(dia.isoformat(), {})
        vento = previsao.get("vento_max_kmh")
        onda = previsao.get("onda_max_m")

        indice = status = janela_a_partir = None
        if cfg.indice_calculavel:  # sem parâmetros com fonte: "sem dado"
            # índice representativo do dia: maré média (menor+maior)/2 + vento/onda máximos previstos
            condicoes = CondicoesAtuais(mare_altura_m=(maior + menor) / 2, vento_kmh=vento, onda_altura_m=onda)
            indice = computar_indice_operacional(condicoes, cfg)
            status = classificar_status(indice)

            pontos = construir_pontos_operacionais(curva, cfg, vento, onda)
            janela = resumir_janela_operacional(pontos, "00:00")
            janela_a_partir = (
                janela["janela_atual"]["inicio_hora"]
                if janela["janela_atual"] and janela["janela_atual"]["status"] == "ideal"
                else janela["melhor_entrada"]
            )

        resultado.append(ResumoDia(
            data=dia.isoformat(), label=_label_do_dia(offset),
            maior_mare_m=round(maior, 2), menor_mare_m=round(menor, 2),
            indice=indice, status=status, janela_a_partir=janela_a_partir,
        ))

    return resultado
