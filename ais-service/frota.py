"""
Frota em destaque (config/frota.json): navios de cabotagem de alguns armadores.

- MMSI: o da lista; senão, o que o AIS informou para aquele IMO
  (ShipStaticData, gravado em navios_info).
- Armador: gravado em navios_info com a fonte da lista — o card do navio
  mostra "armador" com fonte, nunca deduzido do nome.
- Posição: a última gravada no banco nos últimos RETENCAO dias (o mapa geral
  só mostra quem foi ouvido nas últimas 6 h; navio de cabotagem longe das
  antenas fica visível com a idade da posição).
- Rastros compactos (dados/rastros.json): para a análise de schedule no
  navegador (CSV que a pessoa arrasta na tela Schedule, sem subir arquivo).
"""

from __future__ import annotations

import json
import pathlib
from datetime import datetime, timedelta, timezone

from storage import conexao

ARQ_FROTA = pathlib.Path(__file__).parent / "config" / "frota.json"

RASTRO_FROTA_DIAS = 7
RASTRO_OUTROS_DIAS = 3
BALDE_MIN = 10  # no máximo 1 ponto a cada 10 min por navio


def carregar() -> dict:
    if not ARQ_FROTA.exists():
        return {"fonte": None, "armadores": [], "navios": []}
    return json.loads(ARQ_FROTA.read_text(encoding="utf-8"))


def _mmsi_por_imo(imos: list[str]) -> dict[str, str]:
    if not imos:
        return {}
    with conexao() as conn:
        marcas = ",".join("?" * len(imos))
        # o mais recente vence (navio que trocou de bandeira troca de MMSI)
        return dict(conn.execute(
            f"SELECT imo, mmsi FROM navios_info WHERE imo IN ({marcas}) ORDER BY atualizado_em", imos))


def aplicar_armadores(cfg: dict) -> dict[str, dict]:
    """Resolve o MMSI de cada navio e grava o armador (com fonte) em
    navios_info. Devolve {imo: navio com mmsi}."""
    nomes = {a["id"]: a["nome"] for a in cfg["armadores"]}
    achados = _mmsi_por_imo([n["imo"] for n in cfg["navios"]])
    agora = datetime.now(timezone.utc).isoformat()
    navios = {}
    with conexao() as conn:
        for n in cfg["navios"]:
            mmsi = (n.get("mmsi") or "").strip() or achados.get(n["imo"], "")
            navios[n["imo"]] = {**n, "mmsi": mmsi}
            if not mmsi:
                continue
            conn.execute(
                """INSERT INTO navios_info (mmsi, nome_navio, imo, armador, armador_fonte, armador_em, atualizado_em)
                   VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(mmsi) DO UPDATE SET armador = excluded.armador,
                       armador_fonte = excluded.armador_fonte, armador_em = excluded.armador_em,
                       imo = COALESCE(navios_info.imo, excluded.imo),
                       nome_navio = COALESCE(navios_info.nome_navio, excluded.nome_navio)""",
                (mmsi, n["nome"].upper(), n["imo"], nomes.get(n["armador"]), cfg.get("fonte"), agora[:10], agora),
            )
    return navios


def _ultimas(mmsis: list[str], dias: int) -> dict[str, dict]:
    if not mmsis:
        return {}
    desde = (datetime.now(timezone.utc) - timedelta(days=dias)).isoformat()
    marcas = ",".join("?" * len(mmsis))
    with conexao() as conn:
        cur = conn.execute(
            f"""SELECT p.mmsi, p.latitude, p.longitude, p.velocidade_nos, p.rumo, p.proa, p.status_navegacao,
                       p.timestamp_utc, p.nome_navio
                FROM posicoes_navio p JOIN (
                    SELECT mmsi, MAX(timestamp_utc) t FROM posicoes_navio
                    WHERE mmsi IN ({marcas}) AND timestamp_utc >= ? GROUP BY mmsi
                ) u ON p.mmsi = u.mmsi AND p.timestamp_utc = u.t""",
            (*mmsis, desde))
        return {r[0]: {"lat": r[1], "lon": r[2], "sog": r[3], "cog": r[4], "proa": r[5], "status": r[6],
                       "hora": r[7], "nome_ais": r[8]} for r in cur}


def _destinos(mmsis: list[str]) -> dict[str, tuple]:
    if not mmsis:
        return {}
    marcas = ",".join("?" * len(mmsis))
    with conexao() as conn:
        return {r[0]: (r[1], r[2]) for r in conn.execute(
            f"SELECT mmsi, destino, eta_informada FROM navios_info WHERE mmsi IN ({marcas})", mmsis)}


def exportar_frota(cfg: dict, navios: dict[str, dict]) -> dict:
    agora = datetime.now(timezone.utc)
    mmsis = [n["mmsi"] for n in navios.values() if n["mmsi"]]
    ultimas = _ultimas(mmsis, RASTRO_FROTA_DIAS)
    destinos = _destinos(mmsis)
    saida = []
    for n in navios.values():
        p = ultimas.get(n["mmsi"])
        destino, eta = destinos.get(n["mmsi"], (None, None))
        saida.append({
            "imo": n["imo"], "nome": n["nome"], "armador": n["armador"], "mmsi": n["mmsi"] or None,
            "posicao": p,
            "idade_s": int((agora - datetime.fromisoformat(p["hora"])).total_seconds()) if p else None,
            "destino_informado": destino, "eta_informada": eta,
        })
    return {
        "gerado_em": agora.isoformat(),
        "fonte": cfg.get("fonte"),
        "armadores": cfg["armadores"],
        "retencao_dias": RASTRO_FROTA_DIAS,
        "navios": saida,
    }


def exportar_rastros(navios_frota: set[str]) -> dict:
    """{mmsi: [[minuto_epoch, lat*1e4, lon*1e4, sog*10, status], ...]} —
    1 ponto por balde de 10 min; frota 7 dias, demais 3 dias."""
    agora = datetime.now(timezone.utc)
    desde = (agora - timedelta(days=RASTRO_FROTA_DIAS)).isoformat()
    corte_outros = (agora - timedelta(days=RASTRO_OUTROS_DIAS)).isoformat()
    rastros: dict[str, list] = {}
    ultimo_balde: dict[str, int] = {}
    with conexao() as conn:
        cur = conn.execute(
            """SELECT mmsi, latitude, longitude, velocidade_nos, status_navegacao, timestamp_utc
               FROM posicoes_navio WHERE timestamp_utc >= ? ORDER BY mmsi, timestamp_utc""", (desde,))
        for mmsi, lat, lon, sog, status, ts in cur:
            if mmsi not in navios_frota and ts < corte_outros:
                continue
            minuto = int(datetime.fromisoformat(ts).timestamp() // 60)
            balde = minuto // BALDE_MIN
            if ultimo_balde.get(mmsi) == balde:
                continue
            ultimo_balde[mmsi] = balde
            rastros.setdefault(mmsi, []).append([
                minuto, round(lat * 1e4), round(lon * 1e4),
                None if sog is None else round(sog * 10), status,
            ])
    return {
        "gerado_em": agora.isoformat(),
        "formato": "[minuto desde 1970 (UTC), lat×1e4, lon×1e4, velocidade×10 (nós), status AIS]",
        "dias_frota": RASTRO_FROTA_DIAS, "dias_outros": RASTRO_OUTROS_DIAS, "balde_min": BALDE_MIN,
        "navios": rastros,
    }
