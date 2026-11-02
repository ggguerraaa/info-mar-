"""
Orquestrador dos scrapers de praticagem — só os portos com fonte pública
confirmada (Santos e Rio Grande, ver PROJETO.md seção 6). Os demais
portos continuam sem essa camada de confirmação de barra.
"""

from datetime import datetime, timezone

import praticagem_rio_grande
import praticagem_santos
from storage import gravar_barra_status, gravar_fila_manobras

# Mapa: nome do porto (como usado em PORT_CONFIGS) -> função de coleta
_COLETORES = {}
_COLETORES_FILA = {}  # só Rio Grande tem fila de manobras por enquanto


def _coletar_santos() -> tuple[str, bool, str, str | None] | None:
    condicao = praticagem_santos.buscar_condicao_barra()
    if condicao is None:
        return None
    fechada = not praticagem_santos.barra_esta_aberta(condicao)
    return condicao.condicao_barra, fechada, condicao.fonte, condicao.atualizado_em


def _coletar_rio_grande() -> tuple[str, bool, str, str | None] | None:
    condicao = praticagem_rio_grande.buscar_condicao_barra()
    if condicao is None:
        return None
    fechada = not praticagem_rio_grande.barra_esta_praticavel(condicao)
    return condicao.situacao, fechada, condicao.fonte, condicao.desde


def _coletar_fila_rio_grande() -> list[dict]:
    manobras = praticagem_rio_grande.buscar_fila_de_manobras()
    return [
        {
            "navio": m.navio, "tipo_manobra": m.tipo_de_manobra,
            "manobra_de": m.manobra_de, "manobra_para": m.manobra_para, "previsao": m.previsao,
        }
        for m in manobras
    ]


_COLETORES = {
    "Santos": _coletar_santos,
    "Rio Grande": _coletar_rio_grande,
}

_COLETORES_FILA = {
    "Rio Grande": _coletar_fila_rio_grande,
}


def atualizar_barra_de_todos_os_portos_disponiveis() -> None:
    agora = datetime.now(timezone.utc).isoformat()
    for porto, coletor in _COLETORES.items():
        try:
            resultado = coletor()
            if resultado is None:
                print(f"[{agora}] Praticagem de {porto}: nada encontrado (site pode ter mudado layout)")
                continue
            situacao, fechada, fonte, desde = resultado
            gravar_barra_status(porto, situacao, fechada, fonte, desde, agora)
            print(f"[{agora}] Praticagem de {porto}: {situacao} (fechada={fechada})")
        except Exception as exc:  # noqa: BLE001 — scraping externo, não pode derrubar o resto
            print(f"[{agora}] FALHOU ao coletar praticagem de {porto}: {exc}")

    for porto, coletor in _COLETORES_FILA.items():
        try:
            manobras = coletor()
            gravar_fila_manobras(porto, manobras, agora)
            print(f"[{agora}] Fila de manobras de {porto}: {len(manobras)} registros")
        except Exception as exc:  # noqa: BLE001
            print(f"[{agora}] FALHOU ao coletar fila de manobras de {porto}: {exc}")


def porto_tem_fonte_de_praticagem(porto: str) -> bool:
    return porto in _COLETORES


def porto_tem_fila_de_manobras(porto: str) -> bool:
    return porto in _COLETORES_FILA
