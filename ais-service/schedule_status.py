"""
Schedule programado x real (ETA / ETB / ETS).

Entrada: schedule/schedule.csv na raiz do repositório (o dono faz commit dele
todo dia). Saída: dict que vira painel/out/dados/schedule.json.

Regras:
  - Real (ATA/ATB/ATD) sai do rastro gravado no banco (1 posição/min/navio),
    não da hora da rodada.
  - A posição só é aplicada à escala corrente — a primeira ainda não
    encerrada, na ordem da rota. Passar perto de um porto que vem depois não
    gera chegada falsa.
  - Escala não observada: navio já além do porto corrente, a caminho do
    seguinte, com o ETA programado vencido → "passou sem sinal" e a rota avança.
  - Estimado: próximo porto por distância (linha reta × fator de rota) ÷
    velocidade AIS; escalas seguintes herdam o atraso a partir do ETS
    estimado da anterior. ETB/ETS mantêm as janelas programadas.
  - MMSI: coluna do CSV; senão, pelo IMO em navios_info (ShipStaticData).

Estado entre rodadas (eventos já detectados) fica na tabela schedule_eventos.
"""

from __future__ import annotations

import csv
import json
import math
import pathlib
import unicodedata
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from config.port_operations_config import PORT_CONFIGS
from painel_porto import MANAUS
from storage import conexao

RAIZ = pathlib.Path(__file__).resolve().parent.parent
ARQ_SCHEDULE = RAIZ / "schedule" / "schedule.csv"
ARQ_PORTOS_EXTRA = RAIZ / "schedule" / "portos_extra.json"
FUSO = ZoneInfo("America/Sao_Paulo")

CFG = {
    "tolerancia_h": 6,        # |desvio| até isso = no prazo
    "sinal_valido_h": 12,     # posição mais velha que isso não estima nada
    "omissao_h": 24,          # passou isso do ETS sem chegada = possível omissão
    "raio_fundeio_nm": 15,    # entrou aqui = chegou (ATA)
    "raio_berco_nm": 1.5,     # parado aqui = atracou (ATB)
    "sog_parado": 0.5,
    "sog_saida": 3,
    "velocidade_padrao_nos": 12,
    "fator_rota": 1.15,
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS schedule_eventos (
    chave TEXT PRIMARY KEY,      -- NAVIO|VIAGEM|slug
    ata TEXT, atb TEXT, atd TEXT,
    nao_observado TEXT,
    processado_ate TEXT          -- último timestamp de rastro já aplicado
);
"""


# ---------------------------------------------------------------- utilidades

def _iso(dt: datetime | None) -> str | None:
    return dt.astimezone(timezone.utc).isoformat(timespec="minutes") if dt else None


def _de_iso(txt: str | None) -> datetime | None:
    return datetime.fromisoformat(txt) if txt else None


def _data_br(txt: str) -> datetime | None:
    """'dd/mm/aaaa hh:mm', 'dd/mm/aaaa' ou ISO, em hora de Brasília."""
    txt = (txt or "").strip()
    if not txt:
        return None
    for fmt in ("%d/%m/%Y %H:%M", "%d/%m/%Y %H:%M:%S", "%d/%m/%Y", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M"):
        try:
            return datetime.strptime(txt, fmt).replace(tzinfo=FUSO).astimezone(timezone.utc)
        except ValueError:
            pass
    raise ValueError(f"data inválida no schedule: {txt!r}")


def _milhas(lat1, lon1, lat2, lon2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 3440.065 * math.asin(math.sqrt(a))


def _chave_texto(nome: str) -> str:
    return unicodedata.normalize("NFKD", nome).encode("ascii", "ignore").decode().strip().upper()


# ---------------------------------------------------------------- portos

def portos_schedule() -> dict[str, dict]:
    """Portos do painel + MANAUS + os de schedule/portos_extra.json (portos que
    o painel não cobre, ex.: Pecém, Buenos Aires)."""
    portos: dict[str, dict] = {
        slug: {"nome": c.porto, "lat": c.lat, "lon": c.lon, "apelidos": []} for slug, c in PORT_CONFIGS.items()
    }
    portos["manaus"] = {"nome": MANAUS["porto"], "lat": MANAUS["lat"], "lon": MANAUS["lon"],
                        "fator_rota": 1.6, "raio_fundeio_nm": 8, "apelidos": ["BRMAO"]}
    if ARQ_PORTOS_EXTRA.exists():
        for slug, p in json.loads(ARQ_PORTOS_EXTRA.read_text(encoding="utf-8")).items():
            if not slug.startswith("_"):
                portos[slug] = {**portos.get(slug, {}), **p}
    return portos


def _indice_portos(portos: dict) -> dict[str, str]:
    indice = {}
    for slug, p in portos.items():
        for nome in [slug, slug.replace("_", " "), p["nome"], *p.get("apelidos", [])]:
            indice[_chave_texto(nome)] = slug
    return indice


# ---------------------------------------------------------------- schedule

def ler_schedule(portos: dict) -> tuple[list[dict], list[str]]:
    avisos: list[str] = []
    if not ARQ_SCHEDULE.exists():
        return [], ["Sem schedule/schedule.csv no repositório."]
    texto = ARQ_SCHEDULE.read_text(encoding="utf-8-sig")
    sep = ";" if texto.count(";") >= texto.count(",") else ","
    indice = _indice_portos(portos)
    linhas = []
    for n, row in enumerate(csv.DictReader(texto.splitlines(), delimiter=sep), start=2):
        row = {k.strip().lower(): (v or "").strip() for k, v in row.items() if k}
        if not row.get("navio"):
            continue
        slug = indice.get(_chave_texto(row.get("porto", "")))
        if not slug:
            avisos.append(f"Linha {n}: porto '{row.get('porto')}' não reconhecido (cadastre em schedule/portos_extra.json).")
            continue
        try:
            eta, etb, ets = (_data_br(row.get(c, "")) for c in ("eta", "etb", "ets"))
        except ValueError as erro:
            avisos.append(f"Linha {n}: {erro}")
            continue
        linhas.append({
            "navio": row["navio"].upper(),
            "imo": row.get("imo", "").upper().replace("IMO", "").strip(),
            "mmsi": row.get("mmsi", "").strip(),
            "viagem": row.get("viagem", ""),
            "porto": slug,
            "eta": eta, "etb": etb, "ets": ets,
            "omitido": row.get("omitido", "").lower() in ("s", "sim", "x", "1", "true"),
        })
    return linhas, avisos


# ---------------------------------------------------------------- banco

def _resolver_mmsi(linhas: list[dict]) -> None:
    imos = {l["imo"] for l in linhas if l["imo"] and not l["mmsi"]}
    if not imos:
        return
    with conexao() as conn:
        marcas = ",".join("?" * len(imos))
        mapa = dict(conn.execute(
            f"SELECT imo, mmsi FROM navios_info WHERE imo IN ({marcas}) ORDER BY atualizado_em", list(imos)))
    for l in linhas:
        if not l["mmsi"] and l["imo"] in mapa:
            l["mmsi"] = mapa[l["imo"]]


def _rastro(mmsi: str, desde: str) -> list[dict]:
    with conexao() as conn:
        cur = conn.execute(
            """SELECT latitude, longitude, velocidade_nos, status_navegacao, timestamp_utc
               FROM posicoes_navio WHERE mmsi = ? AND timestamp_utc > ? ORDER BY timestamp_utc""",
            (mmsi, desde))
        return [{"lat": r[0], "lon": r[1], "sog": r[2], "status": r[3], "hora": r[4]} for r in cur]


def _ultima_posicao(mmsi: str) -> dict | None:
    with conexao() as conn:
        r = conn.execute(
            """SELECT latitude, longitude, velocidade_nos, status_navegacao, timestamp_utc, rumo
               FROM posicoes_navio WHERE mmsi = ? ORDER BY timestamp_utc DESC LIMIT 1""", (mmsi,)).fetchone()
    return None if not r else {"lat": r[0], "lon": r[1], "sog": r[2], "status": r[3], "hora": r[4], "rumo": r[5]}


def _carregar_eventos() -> dict[str, dict]:
    with conexao() as conn:
        conn.executescript(SCHEMA)
        cur = conn.execute("SELECT chave, ata, atb, atd, nao_observado, processado_ate FROM schedule_eventos")
        return {r[0]: {k: v for k, v in zip(("ata", "atb", "atd", "nao_observado", "processado_ate"), r[1:]) if v}
                for r in cur}


def _salvar_eventos(eventos: dict[str, dict], ativos: set[str]) -> None:
    with conexao() as conn:
        conn.execute("DELETE FROM schedule_eventos")
        conn.executemany(
            "INSERT INTO schedule_eventos VALUES (?, ?, ?, ?, ?, ?)",
            [(k, e.get("ata"), e.get("atb"), e.get("atd"), e.get("nao_observado"), e.get("processado_ate"))
             for k, e in eventos.items() if k in ativos],
        )


# ---------------------------------------------------------------- regras

def _detectar(ev: dict, pos: dict, porto: dict) -> None:
    d = _milhas(pos["lat"], pos["lon"], porto["lat"], porto["lon"])
    raio_f = porto.get("raio_fundeio_nm", CFG["raio_fundeio_nm"])
    raio_b = porto.get("raio_berco_nm", CFG["raio_berco_nm"])
    sog = pos.get("sog") or 0
    if "ata" not in ev and d <= raio_f:
        ev["ata"] = pos["hora"]
    if "ata" in ev and "atb" not in ev and d <= raio_b and (sog < CFG["sog_parado"] or pos.get("status") == 5):
        ev["atb"] = pos["hora"]
    if "atb" in ev and "atd" not in ev and (d > raio_b + 1 or sog > CFG["sog_saida"]):
        ev["atd"] = pos["hora"]


def _aplicar_posicao(chaves: list[str], escalas: list[dict], pos: dict, portos: dict, eventos: dict) -> None:
    """Uma posição vale só para a escala corrente, na ordem da rota."""
    hora = _de_iso(pos["hora"])
    for i, e in enumerate(escalas):
        ev = eventos.setdefault(chaves[i], {})
        if ev.get("atd") or ev.get("nao_observado"):
            continue
        porto = portos[e["porto"]]
        raio = porto.get("raio_fundeio_nm", CFG["raio_fundeio_nm"])
        if not ev.get("ata") and i + 1 < len(escalas) and e["eta"] and hora > e["eta"]:
            prox = portos[escalas[i + 1]["porto"]]
            d_aqui = _milhas(pos["lat"], pos["lon"], porto["lat"], porto["lon"])
            d_pos_prox = _milhas(pos["lat"], pos["lon"], prox["lat"], prox["lon"])
            d_porto_prox = _milhas(porto["lat"], porto["lon"], prox["lat"], prox["lon"])
            if d_aqui > raio and d_pos_prox < d_porto_prox - raio:
                ev["nao_observado"] = pos["hora"]
                continue
        _detectar(ev, pos, porto)
        return


def _desvio(est, prog):
    return round((est - prog).total_seconds() / 3600, 1) if est and prog else None


def _classificar(d: float | None) -> str:
    if d is None:
        return "sem_dado"
    if d > CFG["tolerancia_h"]:
        return "atrasado"
    if d < -CFG["tolerancia_h"]:
        return "adiantado"
    return "no_prazo"


# ---------------------------------------------------------------- principal

def gerar_status() -> dict:
    agora = datetime.now(timezone.utc)
    portos = portos_schedule()
    linhas, avisos = ler_schedule(portos)
    _resolver_mmsi(linhas)
    eventos = _carregar_eventos()

    navios: dict[str, list[dict]] = {}
    for l in linhas:
        navios.setdefault(l["navio"], []).append(l)

    saida, ativos = [], set()
    for nome, todas in navios.items():
        todas.sort(key=lambda e: e["eta"] or e["etb"] or e["ets"] or agora)
        escalas = [e for e in todas if not e["omitido"]]
        chave = lambda e: f'{nome}|{e["viagem"]}|{e["porto"]}'  # noqa: E731
        chaves = [chave(e) for e in escalas]
        ativos.update(chave(e) for e in todas)
        mmsi = next((e["mmsi"] for e in todas if e["mmsi"]), "")

        pos = None
        if mmsi:
            rastro = []
            if escalas:
                # continua de onde a rodada anterior parou; 1ª vez: 2 dias antes do 1º ETA
                feitos = [eventos.get(c, {}).get("processado_ate") for c in chaves]
                if all(feitos):
                    desde = min(feitos)
                else:
                    desde = _iso(min(e["eta"] or agora for e in escalas) - timedelta(days=2))
                rastro = _rastro(mmsi, desde)
            for p in rastro:
                _aplicar_posicao(chaves, escalas, p, portos, eventos)
            if rastro:
                for c in chaves:
                    eventos.setdefault(c, {})["processado_ate"] = rastro[-1]["hora"]
            pos = _ultima_posicao(mmsi)
        idade_h = (agora - _de_iso(pos["hora"])).total_seconds() / 3600 if pos else None
        sinal_ok = idade_h is not None and idade_h <= CFG["sinal_valido_h"]

        linhas_saida = []
        ets_ant_est = ets_ant_prog = None
        proximo_definido = False
        for e in todas:
            p = portos[e["porto"]]
            ev = eventos.get(chave(e), {}) if not e["omitido"] else {}
            ata, atb, atd = (_de_iso(ev.get(k)) for k in ("ata", "atb", "atd"))
            nao_obs = bool(ev.get("nao_observado"))

            eta_est = base = None
            if e["omitido"] or nao_obs:
                pass
            elif ata:
                eta_est, base = ata, "real"
            elif sinal_ok and not proximo_definido:
                dist = _milhas(pos["lat"], pos["lon"], p["lat"], p["lon"]) * p.get("fator_rota", CFG["fator_rota"])
                vel = pos.get("sog") or 0
                if vel < CFG["sog_parado"]:
                    vel, base = CFG["velocidade_padrao_nos"], "velocidade_padrao"
                else:
                    base = "velocidade_ais"
                eta_est = max(_de_iso(pos["hora"]) + timedelta(hours=dist / vel), agora)
            elif ets_ant_est and ets_ant_prog and e["eta"]:
                eta_est, base = ets_ant_est + (e["eta"] - ets_ant_prog), "encadeado"

            etb_est = atb or (eta_est + (e["etb"] - e["eta"]) if eta_est and e["etb"] and e["eta"] else None)
            ets_est = atd or (etb_est + (e["ets"] - e["etb"]) if etb_est and e["ets"] and e["etb"] else None)

            if e["omitido"]:
                situacao = "omitido"
            elif nao_obs:
                situacao = "nao_observado"
            elif atd:
                situacao = "saiu"
            elif atb:
                situacao = "atracado"
            elif ata:
                situacao = "fundeado"
            elif e["ets"] and agora > e["ets"] + timedelta(hours=CFG["omissao_h"]):
                situacao = "possivel_omissao"
            elif not mmsi:
                situacao = "sem_mmsi"
            elif not sinal_ok and base not in ("encadeado",):
                situacao = "sem_sinal"
            else:
                situacao = _classificar(_desvio(eta_est, e["eta"]))

            linhas_saida.append({
                "porto": e["porto"], "porto_nome": p["nome"], "viagem": e["viagem"],
                "programado": {"eta": _iso(e["eta"]), "etb": _iso(e["etb"]), "ets": _iso(e["ets"])},
                "estimado": {"eta": _iso(eta_est), "etb": _iso(etb_est), "ets": _iso(ets_est)},
                "real": {"ata": _iso(ata), "atb": _iso(atb), "atd": _iso(atd)},
                "desvio_h": {"eta": _desvio(eta_est, e["eta"]), "etb": _desvio(etb_est, e["etb"]),
                             "ets": _desvio(ets_est, e["ets"])},
                "base_previsao": base,
                "situacao": situacao,
            })
            if not e["omitido"] and not nao_obs:
                if not atd and situacao != "possivel_omissao":
                    proximo_definido = True
                ets_ant_est = ets_est or ets_ant_est
                ets_ant_prog = e["ets"] or ets_ant_prog

        saida.append({
            "navio": nome,
            "imo": next((e["imo"] for e in todas if e["imo"]), ""),
            "mmsi": mmsi,
            "posicao": pos,
            "sinal_idade_h": round(idade_h, 1) if idade_h is not None else None,
            "escalas": linhas_saida,
        })

    _salvar_eventos(eventos, ativos)
    return {
        "gerado_em": agora.isoformat(),
        "tolerancia_h": CFG["tolerancia_h"],
        "avisos": avisos,
        # completos: o painel usa os mesmos portos e regras para o CSV arrastado no navegador
        "portos": portos,
        "regras": CFG,
        "navios": saida,
    }
