"""
Scraper da praticagem de Rio Grande (RG Pilots) — condição de barra e
dados em tempo real.

Fonte: https://www.rgpilots.com.br/atalaia

A página expõe (aparentemente um debug/print_r não removido em produção)
um array PHP bruto dentro da página com todos os dados estruturados:
condição de barra, maré medida/prevista, estação meteorológica, fases da
lua/sol e pauta de manobras de navio. Isso é MUITO mais robusto de
parsear que as tabelas HTML — usamos regex sobre esse bloco de texto.

Confirmado em 14/09/2026 que o bloco existe e tem exatamente este
formato (print_r do PHP):

    [barra] => Array
        (
            [situacao] => PRATICÁVEL
            [desde] => 09/09/2026 06:30
        )

⚠️ Isso é uma dependência frágil por natureza — se a RG Pilots remover
esse debug output do ar, o scraper para de funcionar e precisa ser
reescrito pra parsear as tabelas HTML visíveis (que também existem na
mesma página, como fallback).
"""

import re
from dataclasses import dataclass

import requests

URL_ATALAIA = "https://www.rgpilots.com.br/atalaia"


@dataclass
class CondicaoBarraRioGrande:
    situacao: str  # ex: "PRATICÁVEL" ou "IMPRATICÁVEL"
    desde: str
    fonte: str = URL_ATALAIA


@dataclass
class EstacaoMeteorologicaRioGrande:
    temperatura_c: float | None
    sensacao_termica_c: float | None
    vento_direcao: str | None
    vento_intensidade_nos: float | None
    pressao_hpa: float | None
    umidade_pct: float | None
    timestamp: str | None


def _extrair_bloco_php(texto: str, chave: str) -> str | None:
    """Extrai o conteúdo de um bloco `[chave] => Array ( ... )` do
    print_r, respeitando parênteses aninhados simples (não recursivo
    até o fim do documento)."""
    padrao = re.compile(rf"\[{re.escape(chave)}\]\s*=>\s*Array\s*\(", re.IGNORECASE)
    m = padrao.search(texto)
    if not m:
        return None

    inicio = m.end()
    profundidade = 1
    i = inicio
    while i < len(texto) and profundidade > 0:
        if texto[i] == "(":
            profundidade += 1
        elif texto[i] == ")":
            profundidade -= 1
        i += 1
    return texto[inicio : i - 1]


def _extrair_campo(bloco: str, campo: str) -> str | None:
    m = re.search(rf"\[{re.escape(campo)}\]\s*=>\s*([^\n\[]+)", bloco)
    return m.group(1).strip() or None if m else None


def buscar_condicao_barra() -> CondicaoBarraRioGrande | None:
    resp = requests.get(URL_ATALAIA, timeout=15)
    resp.raise_for_status()
    texto = resp.text

    bloco = _extrair_bloco_php(texto, "barra")
    if bloco is None:
        return None

    situacao = _extrair_campo(bloco, "situacao")
    desde = _extrair_campo(bloco, "desde")
    if situacao is None:
        return None

    return CondicaoBarraRioGrande(situacao=situacao, desde=desde or "")


def buscar_estacao_meteorologica() -> EstacaoMeteorologicaRioGrande | None:
    resp = requests.get(URL_ATALAIA, timeout=15)
    resp.raise_for_status()
    texto = resp.text

    bloco = _extrair_bloco_php(texto, "vento")
    if bloco is None:
        return None

    def _float(campo: str) -> float | None:
        valor = _extrair_campo(bloco, campo)
        try:
            return float(valor) if valor else None
        except ValueError:
            return None

    return EstacaoMeteorologicaRioGrande(
        temperatura_c=_float("temperatura"),
        sensacao_termica_c=_float("sensacao_termica"),
        vento_direcao=_extrair_campo(bloco, "vento_direcao"),
        vento_intensidade_nos=_float("vento_intensidade"),
        pressao_hpa=_float("pressao"),
        umidade_pct=_float("umidade"),
        timestamp=_extrair_campo(bloco, "timestamp"),
    )


def _extrair_lista_de_blocos_numerados(bloco_pai: str) -> list[str]:
    """Extrai cada sub-bloco `[N] => Array ( ... )` de dentro de um bloco
    maior (ex: a lista de manobras dentro de [atalaia])."""
    blocos = []
    for m in re.finditer(r"\[\d+\]\s*=>\s*Array\s*\(", bloco_pai):
        inicio = m.end()
        profundidade = 1
        i = inicio
        while i < len(bloco_pai) and profundidade > 0:
            if bloco_pai[i] == "(":
                profundidade += 1
            elif bloco_pai[i] == ")":
                profundidade -= 1
            i += 1
        blocos.append(bloco_pai[inicio : i - 1])
    return blocos


@dataclass
class ManobraNavio:
    navio: str
    tipo_de_manobra: str  # 'E' entrada, 'S' saída, 'M' movimentação de berço
    manobra_de: str
    manobra_para: str
    previsao: str  # data/hora prevista da manobra ("pob" no dado original)


def buscar_fila_de_manobras() -> list[ManobraNavio]:
    """Fila de navios (entrada/saída/movimentação de berço) — equivalente
    ao 'fundeados/aguardados/atracados' que outras praticagens expõem em
    páginas separadas. Aqui vem tudo junto no mesmo bloco [atalaia]."""
    resp = requests.get(URL_ATALAIA, timeout=15)
    resp.raise_for_status()
    texto = resp.text

    bloco = _extrair_bloco_php(texto, "atalaia")
    if bloco is None:
        return []

    manobras = []
    for sub_bloco in _extrair_lista_de_blocos_numerados(bloco):
        navio = _extrair_campo(sub_bloco, "navio")
        tipo = _extrair_campo(sub_bloco, "tipo_de_manobra")
        de = _extrair_campo(sub_bloco, "manobra_de")
        para = _extrair_campo(sub_bloco, "manobra_para")
        pob = _extrair_campo(sub_bloco, "pob")
        if navio and tipo:
            manobras.append(ManobraNavio(
                navio=navio, tipo_de_manobra=tipo,
                manobra_de=de or "", manobra_para=para or "", previsao=pob or "",
            ))
    return manobras


def barra_esta_praticavel(condicao: CondicaoBarraRioGrande) -> bool:
    """Normaliza a situação textual pra um booleano simples de usar na
    lógica de índice operacional."""
    return "impraticável" not in condicao.situacao.lower() and "impraticavel" not in condicao.situacao.lower()
