"""
Nível do Rio Negro em Manaus — fonte: telemetria da ANA (estação 14990000);
reserva: portodemanaus.com.br.

Manaus é DELIBERADAMENTE tratado fora do modelo de maré astronômica
(PORT_CONFIGS/tide_now.py): é porto fluvial, sem tábua de maré, e o
"calado máximo" que a SNPH publica (25-45m conforme área) não é
comparável ao calado de canal marítimo dos outros portos — ver nota em
config/port_operations_config.py. Em vez disso, a condição operacional
em Manaus depende do NÍVEL DO RIO, que sobe e desce em escala de
semanas/meses (cheia/seca), não em ciclo de 12h como maré.

A API antiga da ANA usada em versões anteriores do projeto estava
depreciada (não resolvia mais). Hoje a fonte principal é o serviço de
telemetria da ANA (telemetriaws1), atualizado a cada 15 min; o site do
Porto de Manaus publica a régua uma vez por dia e às vezes atrasa dias.

Este módulo é INDEPENDENTE do pipeline de maré (tide_now.py,
mare_ciclo.py) — não tenta encaixar o nível do rio no índice
operacional de 5 faixas usado para os portos marítimos, porque as
escalas de tempo e os riscos operacionais são diferentes (não é
"maré baixa vs alta", é "seca vs cheia").
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger("nivel-rio-manaus")

URL_NIVEL_RIO = "https://portodemanaus.com.br/nivel-do-rio-negro/"
# Reserva (sem cadastro): serviço de telemetria da ANA — doc em
# https://www.ana.gov.br/telemetria1ws/Telemetria1ws.pdf
URL_ANA_TELEMETRIA = "https://telemetriaws1.ana.gov.br/ServiceANA.asmx/DadosHidrometeorologicos"
URL_ANA_FONTE = "https://telemetriaws1.ana.gov.br/ServiceANA.asmx"
ANA_ESTACAO_MANAUS = "14990000"
TIMEOUT_S = 15
USER_AGENT = "InfoMare/1.0 (projeto open source de monitoramento portuário)"


@dataclass
class NivelRioNegro:
    data_leitura: str | None  # "DD/MM/AAAA" como publicado, sem conversão de timezone
    cota_m: float | None
    variacao_cm: float | None  # positivo = enchendo, negativo = vazando
    tendencia: str | None  # "enchendo" | "vazando" | None
    fonte: str = URL_NIVEL_RIO
    coletado_em: str = ""

    def to_dict(self) -> dict:
        return {
            "porto": "manaus",
            "data_leitura": self.data_leitura,
            "cota_m": self.cota_m,
            "variacao_cm": self.variacao_cm,
            "tendencia": self.tendencia,
            "fonte": self.fonte,
            "coletado_em": self.coletado_em,
            "disponivel": self.cota_m is not None,
        }


def _to_float_br(texto: str) -> float | None:
    """Converte número em formato BR ('17,47' ou '17.47') para float.
    A fonte mistura separador decimal entre vírgula e ponto conforme a
    tabela/bloco — normaliza assumindo que o ÚLTIMO separador é o
    decimal (ex.: '1.234,56' -> 1234.56; '17,47' -> 17.47)."""
    texto = texto.strip()
    if not texto:
        return None
    texto = re.sub(r"[^\d,.\-]", "", texto)
    if not texto:
        return None
    if "," in texto and "." in texto:
        if texto.rfind(",") > texto.rfind("."):
            texto = texto.replace(".", "").replace(",", ".")
        else:
            texto = texto.replace(",", "")
    elif "," in texto:
        texto = texto.replace(",", ".")
    try:
        return float(texto)
    except ValueError:
        return None


def _extrair_situacao(texto_pagina: str) -> tuple[str | None, float | None]:
    """Extrai tendência (enchendo/vazando) e variação do dia em cm do
    bloco 'Situação' da página."""
    m = re.search(r"(Encheu|Vazou)\s*:?\s*(-?[\d.,]+)\s*cm", texto_pagina, re.IGNORECASE)
    if not m:
        return None, None
    verbo, valor = m.group(1).lower(), _to_float_br(m.group(2))
    tendencia = "enchendo" if verbo == "encheu" else "vazando"
    if valor is not None and tendencia == "vazando":
        valor = -abs(valor)
    elif valor is not None:
        valor = abs(valor)
    return tendencia, valor


def _extrair_ultima_linha_tabela(soup: BeautifulSoup) -> tuple[str | None, float | None]:
    """Varre as tabelas da página (uma por mês: Dia / Cota (m) /
    Encheu-Vazou) e devolve (data, cota) do maior dia da PRIMEIRA tabela
    com cabeçalho reconhecido. O site lista os meses do mais recente para
    o mais antigo (confirmado em 16/10/2026: 1ª tabela = outubro, até o
    dia 16) — misturar tabelas pegava o dia 31 de um mês antigo."""
    for tabela in soup.find_all("table"):
        cabecalho_texto = " ".join(th.get_text(" ", strip=True).lower() for th in tabela.find_all("th"))
        if "dia" not in cabecalho_texto or "cota" not in cabecalho_texto:
            continue

        melhor_dia: int | None = None
        melhor_cota: float | None = None
        for linha in tabela.find_all("tr"):
            celulas = [c.get_text(" ", strip=True) for c in linha.find_all(["td", "th"])]
            if len(celulas) < 2 or not re.fullmatch(r"\d{1,2}", celulas[0].strip()):
                continue
            dia = int(celulas[0])
            cota = _to_float_br(celulas[1])
            if cota is not None and (melhor_dia is None or dia >= melhor_dia):
                melhor_dia, melhor_cota = dia, cota

        if melhor_dia is None:
            continue
        hoje = datetime.now(timezone.utc)
        return f"{melhor_dia:02d}/{hoje.month:02d}/{hoje.year}", melhor_cota

    return None, None


def _buscar_porto_de_manaus(agora_iso: str) -> NivelRioNegro | None:
    """Fonte principal: régua do Porto de Manaus (a leitura que a operação usa)."""
    try:
        resp = requests.get(
            URL_NIVEL_RIO,
            timeout=TIMEOUT_S,
            headers={"User-Agent": USER_AGENT},
        )
        resp.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        logger.error("Falha ao buscar nível do Rio Negro no site do porto: %s", exc)
        return None

    soup = BeautifulSoup(resp.text, "html.parser")
    texto = soup.get_text(" ", strip=True)
    tendencia, variacao_cm = _extrair_situacao(texto)
    data_leitura, cota_m = _extrair_ultima_linha_tabela(soup)
    # A data vem do cabeçalho "Nível do Rio DD/MM/AAAA": a tabela não traz o
    # mês (em 02/11/2026 a última leitura era 30/10, e o mês atual no lugar
    # dela gerava "30/11", uma data futura).
    cabecalho = re.search(r"N[íi]vel do Rio\s+(\d{2}/\d{2}/\d{4})", texto)
    if cabecalho:
        data_leitura = cabecalho.group(1)
    if cota_m is None:
        logger.warning(
            "Não consegui extrair a cota do Rio Negro da tabela — o HTML do site "
            "pode ter mudado. Verifique _extrair_ultima_linha_tabela em nivel_rio_manaus.py."
        )
        return None
    return NivelRioNegro(data_leitura, cota_m, variacao_cm, tendencia, coletado_em=agora_iso)


def _buscar_ana(agora_iso: str) -> NivelRioNegro | None:
    """Fonte principal: telemetria pública da ANA (sem cadastro), estação
    14990000 (Rio Negro em Manaus), leitura a cada 15 min, nível em CENTÍMETROS.
    Conferido em 16/10/2026: acompanha a régua do porto, mas lê 2-7 cm abaixo
    (sensor/horário diferentes) — o painel mostra a fonte usada."""
    hoje = datetime.now(timezone.utc)
    params = {
        "CodEstacao": ANA_ESTACAO_MANAUS,
        "DataInicio": (hoje - timedelta(days=3)).strftime("%d/%m/%Y"),
        "DataFim": (hoje + timedelta(days=1)).strftime("%d/%m/%Y"),
    }
    try:
        resp = requests.get(URL_ANA_TELEMETRIA, params=params, timeout=TIMEOUT_S * 2)
        resp.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        logger.error("Falha ao buscar nível do Rio Negro na ANA: %s", exc)
        return None

    leituras = []  # [(datetime, cota_cm)], a ANA devolve da mais nova pra mais antiga
    for bloco in re.findall(r"<DadosHidrometereologicos[^>]*>(.*?)</DadosHidrometereologicos>", resp.text, re.S):
        data = re.search(r"<DataHora>\s*([^<]+?)\s*</DataHora>", bloco)
        nivel = re.search(r"<Nivel>\s*([^<]+?)\s*</Nivel>", bloco)
        if data and nivel and _to_float_br(nivel.group(1)) is not None:
            leituras.append((datetime.fromisoformat(data.group(1)), _to_float_br(nivel.group(1))))
    if not leituras:
        logger.warning("ANA respondeu sem leituras de nível pra estação %s.", ANA_ESTACAO_MANAUS)
        return None

    leituras.sort()
    ultima_dt, ultima_cm = leituras[-1]
    # variação em 24h, comparando com a leitura mais próxima de 1 dia antes
    alvo = ultima_dt - timedelta(days=1)
    anterior_dt, anterior_cm = min(leituras, key=lambda l: abs(l[0] - alvo))
    variacao_cm = None
    tendencia = None
    if abs(anterior_dt - alvo) <= timedelta(hours=3):
        variacao_cm = round(ultima_cm - anterior_cm, 1)
        tendencia = "enchendo" if variacao_cm > 0 else "vazando" if variacao_cm < 0 else "estável"

    return NivelRioNegro(
        data_leitura=ultima_dt.strftime("%d/%m/%Y %H:%M"),
        cota_m=round(ultima_cm / 100, 2),
        variacao_cm=variacao_cm,
        tendencia=tendencia,
        fonte=URL_ANA_FONTE,
        coletado_em=agora_iso,
    )


def buscar_nivel_rio_manaus() -> NivelRioNegro:
    """Busca ao vivo: telemetria da ANA (leitura a cada 15 min) e, se falhar,
    o site do Porto de Manaus (atualiza por dia e às vezes atrasa: em
    02/11/2026 a última leitura publicada era de 30/10). Se as duas falharem, devolve um NivelRioNegro com
    campos None em vez de propagar exceção — o endpoint da API trata isso
    como 'disponivel: false', igual ao padrão já usado para praticagem."""
    agora_iso = datetime.now(timezone.utc).isoformat()
    for fonte in (_buscar_ana, _buscar_porto_de_manaus):
        nivel = fonte(agora_iso)
        if nivel is not None:
            return nivel
    return NivelRioNegro(None, None, None, None, coletado_em=agora_iso)


if __name__ == "__main__":
    import json

    logging.basicConfig(level=logging.INFO)
    print(json.dumps(buscar_nivel_rio_manaus().to_dict(), ensure_ascii=False, indent=2))
