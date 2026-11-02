"""
Camada de armazenamento SQLite (data/tabua_mare.db), usada pelo backend
(backend_app.py), pela ingestão AIS (ais_stream.py) e pelos jobs (scheduler.py).

Timestamps são gravados em ISO 8601 UTC ("2026-10-16T20:01:01+00:00").
Comparações de tempo passam por datetime(coluna) — comparar o texto ISO
direto com datetime('now') dá errado ('T' > ' '). Exceção: posicoes_navio,
que cresce muito; ali a comparação é com um ISO gerado em Python
(_iso_ha), mesmo formato, para o índice ser usado.

Modo WAL: exigido pelo Litestream (backup contínuo, ver GUIA-DEPLOY.md) e
deixa a API ler enquanto o coletor grava.
"""

import os
import pathlib
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

DB_PATH = pathlib.Path(os.getenv("DB_PATH") or pathlib.Path(__file__).parent / "data" / "tabua_mare.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS posicoes_navio (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mmsi TEXT NOT NULL,
    nome_navio TEXT,
    latitude REAL NOT NULL,
    longitude REAL NOT NULL,
    velocidade_nos REAL,
    rumo REAL,
    proa REAL,                  -- TrueHeading (null quando o AIS manda 511 = sem dado)
    status_navegacao INTEGER,   -- NavigationalStatus (0-15, ITU-R M.1371)
    timestamp_utc TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_posicoes_mmsi_ts ON posicoes_navio (mmsi, timestamp_utc);
CREATE INDEX IF NOT EXISTS idx_posicoes_timestamp ON posicoes_navio (timestamp_utc);

CREATE TABLE IF NOT EXISTS indice_operacional (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    porto TEXT NOT NULL,
    indice REAL NOT NULL,
    status TEXT NOT NULL,  -- 'ideal' / 'atencao' / 'restrita'
    calculado_em TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_indice_porto ON indice_operacional (porto);

CREATE TABLE IF NOT EXISTS alertas_emitidos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    porto TEXT NOT NULL,
    alerta_id TEXT NOT NULL,   -- 'ressaca' / 'chuva' / 'vento' / 'neblina' / 'mare-excepcional'
    mensagem TEXT NOT NULL,
    severidade TEXT NOT NULL,  -- 'warning' ou 'danger'
    emitido_em TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_alertas_porto ON alertas_emitidos (porto, alerta_id);
CREATE INDEX IF NOT EXISTS idx_alertas_emitido_em ON alertas_emitidos (emitido_em);

CREATE TABLE IF NOT EXISTS barra_status (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    porto TEXT NOT NULL,
    situacao TEXT NOT NULL,   -- texto original da praticagem: "barra aberta", "PRATICÁVEL", etc.
    fechada INTEGER NOT NULL, -- 0/1 já normalizado, pra facilitar a lógica de override
    fonte TEXT,
    desde TEXT,               -- desde quando essa situação vale (quando a fonte informa)
    coletado_em TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_barra_porto ON barra_status (porto);

-- De/para MMSI <-> nome <-> IMO montado a partir do ShipStaticData do AIS
-- (chega de vez em quando, não em toda mensagem). Armador NÃO vem do AIS:
-- só é preenchido com fonte registrada (armador_fonte + armador_em).
CREATE TABLE IF NOT EXISTS navios_info (
    mmsi TEXT PRIMARY KEY,
    nome_navio TEXT,
    imo TEXT,
    indicativo TEXT,            -- CallSign
    tipo_codigo INTEGER,        -- Type (ITU-R M.1371, ver tipos_navio.py)
    comprimento_m REAL,         -- Dimension A + B
    boca_m REAL,                -- Dimension C + D
    calado_max_m REAL,          -- MaximumStaticDraught (informado pela tripulação)
    destino TEXT,               -- Destination (texto livre, informado pela tripulação)
    eta_informada TEXT,         -- Eta "MM-DD HH:MM" (o AIS não manda o ano)
    armador TEXT,
    armador_fonte TEXT,
    armador_em TEXT,
    atualizado_em TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_navios_info_imo ON navios_info (imo);
CREATE INDEX IF NOT EXISTS idx_navios_info_nome ON navios_info (nome_navio);

-- Períodos em que o listener AIS estava conectado. Fora deles, ausência de
-- posição é lacuna de coleta, não "navio sumiu" (o AIS não tem histórico).
CREATE TABLE IF NOT EXISTS coleta_ais (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    inicio TEXT NOT NULL,
    ultimo_sinal TEXT NOT NULL,
    fim TEXT,
    motivo_fim TEXT
);

CREATE TABLE IF NOT EXISTS fila_manobras (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    porto TEXT NOT NULL,
    navio TEXT NOT NULL,
    tipo_manobra TEXT NOT NULL,  -- 'E' entrada, 'S' saida, 'M' movimentacao de berco
    manobra_de TEXT,
    manobra_para TEXT,
    previsao TEXT,               -- data/hora prevista, como veio da fonte
    coletado_em TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_fila_manobras_porto ON fila_manobras (porto, coletado_em);
"""

# Bancos criados por versões anteriores: colunas que entram / saem.
_COLUNAS_NOVAS = {
    "posicoes_navio": {"proa": "REAL", "status_navegacao": "INTEGER"},
    "navios_info": {
        "indicativo": "TEXT", "tipo_codigo": "INTEGER", "boca_m": "REAL", "calado_max_m": "REAL",
        "destino": "TEXT", "eta_informada": "TEXT", "armador": "TEXT", "armador_fonte": "TEXT",
        "armador_em": "TEXT",
    },
}
_COLUNAS_REMOVIDAS = {
    # empresa era inferida pelo prefixo do nome — proibido (sem fonte)
    "navios_info": ["empresa", "tipo_navio"],
    "alertas_emitidos": ["enviado_telegram"],
}
_INDICES_REMOVIDOS = ["idx_navios_info_empresa", "idx_posicoes_mmsi"]  # mmsi sozinho: coberto por (mmsi, ts)


def _iso_ha(**delta) -> str:
    return (datetime.now(timezone.utc) - timedelta(**delta)).isoformat()


@contextmanager
def conexao():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.execute("PRAGMA synchronous=NORMAL")  # seguro em WAL, bem mais rápido
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _migrar(conn: sqlite3.Connection) -> None:
    for indice in _INDICES_REMOVIDOS:
        conn.execute(f"DROP INDEX IF EXISTS {indice}")
    for tabela, colunas in _COLUNAS_NOVAS.items():
        existentes = {r[1] for r in conn.execute(f"PRAGMA table_info({tabela})")}
        for nome, tipo in colunas.items():
            if nome not in existentes:
                conn.execute(f"ALTER TABLE {tabela} ADD COLUMN {nome} {tipo}")
    for tabela, colunas in _COLUNAS_REMOVIDAS.items():
        existentes = {r[1] for r in conn.execute(f"PRAGMA table_info({tabela})")}
        for nome in colunas:
            if nome in existentes:
                conn.execute(f"ALTER TABLE {tabela} DROP COLUMN {nome}")


def inicializar_banco() -> None:
    with conexao() as conn:
        conn.execute("PRAGMA journal_mode=WAL")  # persiste no arquivo
        conn.executescript(SCHEMA)
        _migrar(conn)
        # índices que dependem de colunas criadas na migração
        conn.execute("CREATE INDEX IF NOT EXISTS idx_navios_info_imo ON navios_info (imo)")


# ---------------------------------------------------------------- AIS

_COLUNAS_POSICAO = ("mmsi", "nome_navio", "latitude", "longitude", "velocidade_nos", "rumo", "proa",
                    "status_navegacao", "timestamp_utc")
_COLUNAS_INFO = ("mmsi", "nome_navio", "imo", "indicativo", "tipo_codigo", "comprimento_m", "boca_m",
                 "calado_max_m", "destino", "eta_informada", "atualizado_em")


def gravar_posicoes(posicoes: list[dict]) -> None:
    """Grava um lote de posições (o coletor junta e grava a cada ~10 s —
    uma conexão por mensagem não aguenta a costa inteira)."""
    if not posicoes:
        return
    with conexao() as conn:
        conn.executemany(
            f"INSERT INTO posicoes_navio ({', '.join(_COLUNAS_POSICAO)}) VALUES ({', '.join('?' * len(_COLUNAS_POSICAO))})",
            [tuple(p.get(c) for c in _COLUNAS_POSICAO) for p in posicoes],
        )


def gravar_infos(infos: list[dict]) -> None:
    """UPSERT em lote dos dados estáticos. Campo que chega vazio NÃO apaga o
    valor já conhecido (COALESCE) — o ShipStaticData às vezes vem incompleto, e
    navio visto só por posição entra só com o nome (MetaData.ShipName).
    Os campos de armador não são tocados aqui (não vêm do AIS)."""
    if not infos:
        return
    with conexao() as conn:
        conn.executemany(
            f"""INSERT INTO navios_info ({', '.join(_COLUNAS_INFO)})
               VALUES ({', '.join('?' * len(_COLUNAS_INFO))})
               ON CONFLICT(mmsi) DO UPDATE SET
                 nome_navio=COALESCE(excluded.nome_navio, nome_navio),
                 imo=COALESCE(excluded.imo, imo),
                 indicativo=COALESCE(excluded.indicativo, indicativo),
                 tipo_codigo=COALESCE(excluded.tipo_codigo, tipo_codigo),
                 comprimento_m=COALESCE(excluded.comprimento_m, comprimento_m),
                 boca_m=COALESCE(excluded.boca_m, boca_m),
                 calado_max_m=COALESCE(excluded.calado_max_m, calado_max_m),
                 destino=COALESCE(excluded.destino, destino),
                 eta_informada=COALESCE(excluded.eta_informada, eta_informada),
                 atualizado_em=excluded.atualizado_em""",
            [tuple(i.get(c) for c in _COLUNAS_INFO) for i in infos],
        )


def obter_info_navios_por_mmsi(mmsis: list[str]) -> dict[str, dict]:
    if not mmsis:
        return {}
    resultado: dict[str, dict] = {}
    with conexao() as conn:
        conn.row_factory = sqlite3.Row
        # SQLite limita o número de parâmetros por consulta — vai em lotes
        for i in range(0, len(mmsis), 500):
            lote = mmsis[i : i + 500]
            placeholders = ",".join("?" for _ in lote)
            for row in conn.execute(f"SELECT * FROM navios_info WHERE mmsi IN ({placeholders})", lote):
                resultado[row["mmsi"]] = dict(row)
    return resultado


def buscar_navios(termo: str, limite: int = 20) -> list[dict]:
    """Busca por nome (parcial), MMSI ou IMO (começo do número) entre os
    navios já vistos. Só em navios_info: todo navio com posição entra lá ao
    menos com o nome, então não é preciso varrer posicoes_navio."""
    termo = termo.strip()
    if not termo:
        return []
    with conexao() as conn:
        conn.row_factory = sqlite3.Row
        if termo.isdigit():
            cursor = conn.execute(
                """SELECT * FROM navios_info WHERE mmsi LIKE ? OR imo LIKE ?
                   ORDER BY (mmsi = ? OR imo = ?) DESC, atualizado_em DESC LIMIT ?""",
                (f"{termo}%", f"{termo}%", termo, termo, limite),
            )
        else:
            nome = termo.upper()
            cursor = conn.execute(
                """SELECT * FROM navios_info WHERE nome_navio LIKE ?
                   ORDER BY (nome_navio LIKE ?) DESC, nome_navio LIMIT ?""",
                (f"%{nome}%", f"{nome}%", limite),
            )
        return [dict(r) for r in cursor]


def navios_com_destino(desde_horas: int = 72) -> list[dict]:
    """Destinos informados recentemente — para "a caminho" no painel do porto."""
    with conexao() as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.execute(
            """SELECT mmsi, nome_navio, destino, eta_informada FROM navios_info
               WHERE destino IS NOT NULL AND datetime(atualizado_em) >= datetime('now', ?)""",
            (f"-{desde_horas} hours",),
        )
        return [dict(r) for r in cursor]


def obter_posicoes_recentes(horas: int = 6) -> list[dict]:
    """Última posição gravada de cada navio dentro da janela — reabastece a
    memória do coletor quando o backend sobe (reinício no Render)."""
    with conexao() as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.execute(
            """SELECT p.* FROM posicoes_navio p
               INNER JOIN (
                   SELECT mmsi, MAX(timestamp_utc) AS max_ts
                   FROM posicoes_navio WHERE timestamp_utc >= ?
                   GROUP BY mmsi
               ) ultimo ON p.mmsi = ultimo.mmsi AND p.timestamp_utc = ultimo.max_ts""",
            (_iso_ha(hours=horas),),
        )
        return [dict(row) for row in cursor.fetchall()]


def obter_trajetoria(mmsi: str, limite: int = 2000, horas: int = 24, mais_recentes: bool = False) -> list[dict]:
    """Histórico de posições de um navio (mais antigo primeiro) — rastro e ETA.
    mais_recentes=True: as `limite` últimas, mais nova primeiro."""
    with conexao() as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.execute(
            f"""SELECT nome_navio, latitude, longitude, velocidade_nos, rumo, proa, status_navegacao, timestamp_utc
               FROM posicoes_navio
               WHERE mmsi = ? AND timestamp_utc >= ?
               ORDER BY timestamp_utc {'DESC' if mais_recentes else 'ASC'} LIMIT ?""",
            (mmsi, _iso_ha(hours=horas), limite),
        )
        return [dict(row) for row in cursor.fetchall()]


def apagar_posicoes_antigas(dias: int = 7) -> int:
    with conexao() as conn:
        cursor = conn.execute("DELETE FROM posicoes_navio WHERE timestamp_utc < ?", (_iso_ha(days=dias),))
        return cursor.rowcount


def contar_registros() -> dict:
    """Tamanho do banco, para o log de medição (instância gratuita tem pouco espaço)."""
    with conexao() as conn:
        return {
            "posicoes": conn.execute("SELECT COUNT(*) FROM posicoes_navio").fetchone()[0],
            "navios": conn.execute("SELECT COUNT(*) FROM navios_info").fetchone()[0],
            "bytes": DB_PATH.stat().st_size if DB_PATH.exists() else 0,
        }


def abrir_periodo_coleta(agora: str) -> int:
    with conexao() as conn:
        # período que ficou aberto (backend morto sem fechar) termina no último sinal
        conn.execute(
            "UPDATE coleta_ais SET fim = ultimo_sinal, motivo_fim = 'interrompido' WHERE fim IS NULL"
        )
        cursor = conn.execute("INSERT INTO coleta_ais (inicio, ultimo_sinal) VALUES (?, ?)", (agora, agora))
        return cursor.lastrowid


def registrar_sinal_coleta(periodo_id: int, agora: str) -> None:
    with conexao() as conn:
        conn.execute("UPDATE coleta_ais SET ultimo_sinal = ? WHERE id = ?", (agora, periodo_id))


def fechar_periodo_coleta(periodo_id: int, agora: str, motivo: str) -> None:
    with conexao() as conn:
        conn.execute(
            "UPDATE coleta_ais SET ultimo_sinal = ?, fim = ?, motivo_fim = ? WHERE id = ?",
            (agora, agora, motivo, periodo_id),
        )


def listar_periodos_coleta(dias: int = 7) -> list[dict]:
    with conexao() as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.execute(
            """SELECT inicio, COALESCE(fim, ultimo_sinal) AS fim, fim IS NULL AS ativo, motivo_fim
               FROM coleta_ais WHERE datetime(COALESCE(fim, ultimo_sinal)) >= datetime('now', ?)
               ORDER BY inicio""",
            (f"-{dias} days",),
        )
        return [dict(r) for r in cursor]


# ------------------------------------------------- índice e alertas


def gravar_indice_operacional(porto: str, indice: float, status: str, calculado_em: str) -> None:
    with conexao() as conn:
        conn.execute(
            """INSERT INTO indice_operacional (porto, indice, status, calculado_em)
               VALUES (?, ?, ?, ?)""",
            (porto, indice, status, calculado_em),
        )


def alerta_ja_emitido_recentemente(porto: str, alerta_id: str, janela_horas: int = 3) -> bool:
    """Evita regravar o mesmo alerta a cada ciclo do scheduler (30 min)."""
    with conexao() as conn:
        cursor = conn.execute(
            """SELECT COUNT(*) FROM alertas_emitidos
               WHERE porto = ? AND alerta_id = ?
               AND datetime(emitido_em) >= datetime('now', ?)""",
            (porto, alerta_id, f"-{janela_horas} hours"),
        )
        return cursor.fetchone()[0] > 0


def gravar_alerta(porto: str, alerta_id: str, mensagem: str, severidade: str, emitido_em: str) -> int:
    with conexao() as conn:
        cursor = conn.execute(
            """INSERT INTO alertas_emitidos (porto, alerta_id, mensagem, severidade, emitido_em)
               VALUES (?, ?, ?, ?, ?)""",
            (porto, alerta_id, mensagem, severidade, emitido_em),
        )
        return cursor.lastrowid


def listar_alertas_recentes(limite: int = 30) -> list[dict]:
    with conexao() as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.execute("SELECT * FROM alertas_emitidos ORDER BY emitido_em DESC LIMIT ?", (limite,))
        return [dict(row) for row in cursor.fetchall()]


def listar_alertas_por_porto(porto: str, limite: int = 10) -> list[dict]:
    with conexao() as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.execute(
            "SELECT * FROM alertas_emitidos WHERE porto = ? ORDER BY emitido_em DESC LIMIT ?", (porto, limite)
        )
        return [dict(row) for row in cursor.fetchall()]


def obter_ultimo_indice_por_porto() -> dict[str, dict]:
    with conexao() as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.execute(
            """SELECT i.* FROM indice_operacional i
               INNER JOIN (
                   SELECT porto, MAX(calculado_em) AS max_ts
                   FROM indice_operacional
                   GROUP BY porto
               ) ultimo ON i.porto = ultimo.porto AND i.calculado_em = ultimo.max_ts"""
        )
        return {row["porto"]: dict(row) for row in cursor.fetchall()}


def obter_historico_indice(porto: str, dias: int = 7) -> list[dict]:
    with conexao() as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.execute(
            """SELECT indice, status, calculado_em FROM indice_operacional
               WHERE porto = ? AND datetime(calculado_em) >= datetime('now', ?)
               ORDER BY calculado_em ASC""",
            (porto, f"-{dias} days"),
        )
        return [dict(row) for row in cursor.fetchall()]


def obter_eventos_mudanca_status(porto: str, limite: int = 10) -> list[dict]:
    """'Últimos eventos' (status mudou para X), derivados de linhas
    consecutivas de indice_operacional — gravado a cada 30 min."""
    with conexao() as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.execute(
            "SELECT status, calculado_em FROM indice_operacional WHERE porto = ? ORDER BY calculado_em ASC",
            (porto,),
        )
        linhas = [dict(row) for row in cursor.fetchall()]

    eventos = []
    status_anterior = None
    for linha in linhas:
        if status_anterior is not None and linha["status"] != status_anterior:
            eventos.append({"horario": linha["calculado_em"], "descricao": f"Status mudou para {linha['status']}"})
        status_anterior = linha["status"]
    return list(reversed(eventos))[:limite]


# ------------------------------------------------------- praticagem


def gravar_barra_status(porto: str, situacao: str, fechada: bool, fonte: str | None, desde: str | None, coletado_em: str) -> None:
    with conexao() as conn:
        conn.execute(
            """INSERT INTO barra_status (porto, situacao, fechada, fonte, desde, coletado_em)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (porto, situacao, int(fechada), fonte, desde, coletado_em),
        )


def obter_ultima_barra_status(porto: str) -> dict | None:
    with conexao() as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM barra_status WHERE porto = ? ORDER BY coletado_em DESC LIMIT 1", (porto,)
        ).fetchone()
        return dict(row) if row else None


def gravar_fila_manobras(porto: str, manobras: list[dict], coletado_em: str) -> None:
    """Substitui a fila anterior desse porto pela mais recente — é sempre 'a fila de agora'."""
    with conexao() as conn:
        conn.execute("DELETE FROM fila_manobras WHERE porto = ?", (porto,))
        conn.executemany(
            """INSERT INTO fila_manobras (porto, navio, tipo_manobra, manobra_de, manobra_para, previsao, coletado_em)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            [
                (porto, m["navio"], m["tipo_manobra"], m["manobra_de"], m["manobra_para"], m["previsao"], coletado_em)
                for m in manobras
            ],
        )


def obter_fila_manobras(porto: str) -> list[dict]:
    with conexao() as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.execute("SELECT * FROM fila_manobras WHERE porto = ? ORDER BY previsao ASC", (porto,))
        return [dict(row) for row in cursor.fetchall()]


if __name__ == "__main__":
    inicializar_banco()
    print(f"Banco inicializado em {DB_PATH}")
