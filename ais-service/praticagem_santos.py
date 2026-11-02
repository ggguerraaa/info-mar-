"""
Scraper da praticagem de Santos (Santos Pilots) — condição de barra.

Fonte: https://login.sppilots.com.br/santos

Confirmado em 14/09/2026 que a página traz (via texto extraído, layout
provavelmente em cards Wix/Bootstrap — heading + valor logo abaixo):

    ##### Condição da Barra
    barra aberta

    ##### Condição da Praticagem
    praticagem indireta

    ##### Fase da Lua
    Lua Nova (11/09/2026)

    Atualizado em 14/09/2026 as 23:49

⚠️ IMPORTANTE: esta implementação usa busca por TEXTO do heading (não
por classe/id CSS), porque não tive acesso à árvore DOM crua pra
confirmar os seletores exatos — só ao conteúdo já extraído em texto.
Ao rodar isso localmente pela primeira vez, comparar o resultado com o
que aparece no navegador; se a busca por texto falhar (heading com
espaços/HTML extra), inspecionar o HTML real (Ctrl+U ou DevTools) e
trocar por um seletor CSS específico (ex: `soup.select_one('.classe')`).
"""

import re
from dataclasses import dataclass

import requests
from bs4 import BeautifulSoup

URL_SANTOS = "https://login.sppilots.com.br/santos"


@dataclass
class CondicaoBarraSantos:
    condicao_barra: str  # ex: "barra aberta" / "barra fechada"
    condicao_praticagem: str | None  # ex: "praticagem normal" / "praticagem indireta"
    atualizado_em: str | None
    fonte: str = URL_SANTOS


def _texto_apos_heading(soup: BeautifulSoup, texto_heading: str) -> str | None:
    """Acha um elemento cujo texto (stripped) bate com `texto_heading`
    e retorna o texto do próximo elemento irmão não vazio."""
    for tag in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "strong", "b", "p", "div"]):
        if tag.get_text(strip=True).lower() == texto_heading.lower():
            proximo = tag.find_next_sibling()
            tentativas = 0
            while proximo is not None and not proximo.get_text(strip=True) and tentativas < 3:
                proximo = proximo.find_next_sibling()
                tentativas += 1
            if proximo is not None:
                return proximo.get_text(strip=True)
    return None


def buscar_condicao_barra() -> CondicaoBarraSantos | None:
    resp = requests.get(URL_SANTOS, timeout=15)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    condicao_barra = _texto_apos_heading(soup, "Condição da Barra")
    if condicao_barra is None:
        return None

    condicao_praticagem = _texto_apos_heading(soup, "Condição da Praticagem")

    # "Atualizado em 14/09/2026 as 23:49" aparece como texto solto na página
    match_atualizado = re.search(r"Atualizado em [\d/]+ as [\d:]+", soup.get_text())
    atualizado_em = match_atualizado.group(0) if match_atualizado else None

    return CondicaoBarraSantos(
        condicao_barra=condicao_barra,
        condicao_praticagem=condicao_praticagem,
        atualizado_em=atualizado_em,
    )


def barra_esta_aberta(condicao: CondicaoBarraSantos) -> bool:
    return "fechada" not in condicao.condicao_barra.lower()
