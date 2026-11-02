"""
Verificação do AISstream na caixa real do coletor (a documentação não lista
tudo o que chega).

Conecta SEM filtro de tipo de mensagem e SEM filtro de navio, na mesma caixa
do coletor (AIS_CAIXAS do .env ou o padrão lat -56..6, lon -73..-25), e por
N segundos:
  - conta mensagens por tipo e quantos navios distintos cada tipo traz
  - mede mensagens por segundo (total e por minuto)
  - imprime 2 amostras brutas de cada tipo
  - mede quantos navios chegam com nome e IMO (ShipStaticData) e com nome
    (StaticDataReport, Classe B)

Uso:  python tools/verificar_ais.py [segundos]   (padrão 300)

O AISstream aceita um coletor por chave: pare o backend local antes, senão
um dos dois recebe 429.
"""

import asyncio
import json
import os
import sys
import time
from collections import Counter, defaultdict

import websockets
from dotenv import load_dotenv

load_dotenv()
CHAVE = os.getenv("AISSTREAM_API_KEY", "")
URL = "wss://stream.aisstream.io/v0/stream"
CAIXAS = json.loads(os.getenv("AIS_CAIXAS", "") or "null") or [[[-56.0, -73.0], [6.0, -25.0]]]


def _tem_posicao(corpo: dict) -> bool:
    lat, lon = corpo.get("Latitude"), corpo.get("Longitude")
    return lat is not None and lon is not None and abs(lat) <= 90 and abs(lon) <= 180


async def main(segundos: int) -> None:
    if not CHAVE:
        sys.exit("AISSTREAM_API_KEY ausente no .env")

    tipos: Counter = Counter()
    navios_por_tipo: dict[str, set] = defaultdict(set)
    tipos_com_posicao: Counter = Counter()
    amostras: dict[str, list] = defaultdict(list)
    por_minuto: Counter = Counter()
    bytes_total = 0
    estaticos: dict[str, dict] = {}   # ShipStaticData (Classe A)
    classe_b_nome: dict[str, str] = {}  # StaticDataReport parte A

    print(f"caixas: {CAIXAS}  duração: {segundos}s", flush=True)
    inicio = time.monotonic()
    async with websockets.connect(URL, open_timeout=15, max_size=2**22) as ws:
        await ws.send(json.dumps({"APIKey": CHAVE, "BoundingBoxes": CAIXAS}))
        while time.monotonic() - inicio < segundos:
            try:
                bruto = await asyncio.wait_for(ws.recv(), timeout=5)
            except TimeoutError:
                continue
            bytes_total += len(bruto)
            msg = json.loads(bruto)
            tipo = msg.get("MessageType") or ("erro" if "error" in msg else "?")
            if tipo in ("SubscriptionConfirmation", "erro"):
                print(tipo, msg, flush=True)
                continue
            tipos[tipo] += 1
            por_minuto[int((time.monotonic() - inicio) // 60)] += 1
            mmsi = str(msg.get("MetaData", {}).get("MMSI"))
            navios_por_tipo[tipo].add(mmsi)
            corpo = (msg.get("Message") or {}).get(tipo) or {}
            if _tem_posicao(corpo):
                tipos_com_posicao[tipo] += 1
            if len(amostras[tipo]) < 2:
                amostras[tipo].append(msg)
            if tipo == "ShipStaticData":
                estaticos[mmsi] = corpo
            elif tipo == "StaticDataReport":
                nome = ((corpo.get("ReportA") or {}).get("Name") or "").replace("@", "").strip()
                if nome:
                    classe_b_nome[mmsi] = nome

    duracao = time.monotonic() - inicio
    for tipo, msgs in amostras.items():
        print(f"\n===== amostras de {tipo} =====")
        for m in msgs:
            print(json.dumps(m, ensure_ascii=False)[:1500])

    total = sum(tipos.values())
    print(f"\n===== Resumo ({duracao:.0f}s) =====")
    print(f"mensagens: {total}  ->  {total / duracao:.1f} msg/s  ({bytes_total / duracao / 1024:.1f} KiB/s)")
    print(f"mensagens por minuto: {[por_minuto[m] for m in sorted(por_minuto)]}")
    print(f"{'tipo':45} {'msgs':>7} {'msg/s':>7} {'navios':>7} {'c/ posição':>11}")
    for tipo, n in tipos.most_common():
        print(f"{tipo:45} {n:7} {n / duracao:7.2f} {len(navios_por_tipo[tipo]):7} {tipos_com_posicao[tipo]:11}")

    com_pos = set().union(*(navios_por_tipo[t] for t in tipos_com_posicao)) if tipos_com_posicao else set()
    so_pr = navios_por_tipo.get("PositionReport", set())
    print(f"\nnavios distintos com posição (qualquer tipo): {len(com_pos)}")
    print(f"  só via PositionReport (Classe A): {len(so_pr)}")
    print(f"  a mais com os outros tipos: {len(com_pos - so_pr)}")
    com_imo = sum(1 for s in estaticos.values() if s.get("ImoNumber"))
    com_nome = sum(1 for s in estaticos.values() if (s.get("Name") or "").replace("@", "").strip())
    print(f"ShipStaticData: {len(estaticos)} navios (nome: {com_nome}, IMO: {com_imo})")
    print(f"StaticDataReport (Classe B) com nome: {len(classe_b_nome)} navios")


if __name__ == "__main__":
    asyncio.run(main(int(sys.argv[1]) if len(sys.argv) > 1 else 300))
