"""
Calculadora de calado / UKC (Under Keel Clearance) — porta de
DraftCalculator.tsx do fork MareAgora (GPL, só a lógica foi portada).

Varre a curva de maré do dia e acha as janelas em que:
    zero_hidrografico + altura_mare >= calado_navio + margem_ukc
"""

import json
import pathlib
from datetime import date

DATA_DIR = pathlib.Path(__file__).parent / "data" / "mare"


def _zero_hidrografico(dhn_id: str) -> float | None:
    caminho = DATA_DIR / f"{dhn_id}.json"
    if not caminho.exists():
        return None
    dados = json.loads(caminho.read_text(encoding="utf-8"))
    return dados.get("metadata", {}).get("nivel_medio_m")


def calcular_janelas_seguras(
    dhn_id: str, curva_mare: list[dict], calado_navio_m: float, margem_ukc_m: float = 0.5
) -> dict:
    profundidade_necessaria = calado_navio_m + margem_ukc_m
    zero_hidro = _zero_hidrografico(dhn_id)

    if zero_hidro is None or not curva_mare:
        return {
            "profundidade_necessaria_m": profundidade_necessaria,
            "zero_hidrografico_m": zero_hidro,
            "janelas": [],
            "aviso": "Sem dado de zero hidrográfico ou maré do dia — ver tools/gerar_tabua_harmonica.py",
        }

    janelas = []
    inicio_atual = None
    for ponto in curva_mare:
        profundidade_disponivel = zero_hidro + ponto["altura_m"]
        seguro = profundidade_disponivel >= profundidade_necessaria

        if seguro and inicio_atual is None:
            inicio_atual = ponto["hora"]
        elif not seguro and inicio_atual is not None:
            janelas.append({"inicio": inicio_atual, "fim": ponto["hora"]})
            inicio_atual = None

    if inicio_atual is not None:
        janelas.append({"inicio": inicio_atual, "fim": "23:59"})

    return {
        "profundidade_necessaria_m": round(profundidade_necessaria, 2),
        "zero_hidrografico_m": zero_hidro,
        "janelas": janelas,
    }
