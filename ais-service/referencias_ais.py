"""
Tabelas de referência para traduzir códigos do AIS em texto.

- Tipo de navio e status de navegação: Recomendação ITU-R M.1371
  (tabela "Type of ship" e campo "Navigational status" da mensagem 1/2/3).
- Bandeira: os 3 primeiros dígitos do MMSI (MID), pela tabela oficial da
  ITU em config/mid_itu.json (fonte e data dentro do arquivo).
"""

import json
import pathlib
from functools import lru_cache

_MID_PATH = pathlib.Path(__file__).parent / "config" / "mid_itu.json"

STATUS_NAVEGACAO = {
    0: "Em navegação a motor",
    1: "Fundeado",
    2: "Sem governo",
    3: "Manobrabilidade restrita",
    4: "Restrito pelo calado",
    5: "Atracado",
    6: "Encalhado",
    7: "Em pesca",
    8: "Em navegação a vela",
    11: "Rebocando à ré",
    12: "Empurrando à vante / rebocando a contrabordo",
    14: "AIS-SART / MOB / EPIRB ativo",
}  # 9, 10, 13 reservados; 15 = não definido -> sem dado


def nome_status(codigo: int | None) -> str | None:
    return STATUS_NAVEGACAO.get(codigo) if codigo is not None else None


def nome_tipo(codigo: int | None) -> str | None:
    """Faixas da ITU-R M.1371. 0 = não informado."""
    if not codigo:
        return None
    especificos = {
        30: "Pesqueiro", 31: "Rebocador (reboque)", 32: "Rebocador (reboque grande)", 33: "Dragagem / obras",
        34: "Mergulho", 35: "Militar", 36: "Veleiro", 37: "Recreio", 50: "Lancha de praticagem",
        51: "Busca e salvamento", 52: "Rebocador", 53: "Apoio portuário", 54: "Combate à poluição",
        55: "Autoridade policial", 58: "Transporte médico", 59: "Navio de estado não combatente",
    }
    if codigo in especificos:
        return especificos[codigo]
    faixas = [
        (20, 29, "Embarcação de efeito-solo (WIG)"), (40, 49, "Alta velocidade (HSC)"),
        (60, 69, "Passageiros"), (70, 79, "Carga"), (80, 89, "Tanque"), (90, 99, "Outros"),
    ]
    for ini, fim, nome in faixas:
        if ini <= codigo <= fim:
            return nome
    return None


@lru_cache(maxsize=1)
def _mids() -> dict[str, str]:
    return json.loads(_MID_PATH.read_text(encoding="utf-8"))["mids"]


def bandeira_por_mmsi(mmsi: str | None) -> str | None:
    """MMSI de navio tem 9 dígitos e começa pelo MID. Outros formatos
    (estação costeira 00…, SAR 111…, auxílios à navegação 99…) não têm
    bandeira de navio -> sem dado."""
    if not mmsi or len(mmsi) != 9 or not mmsi.isdigit() or mmsi[0] in "019":
        return None
    return _mids().get(mmsi[:3])
