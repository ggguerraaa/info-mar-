"""
ETA (tempo estimado de chegada) de um navio até um porto — peça que
ficou pendente desde o início do projeto (a "frente MarineTraffic" só
tinha posição/velocidade, sem cruzar com destino).

Método: distância em linha reta (haversine) entre a posição atual do
navio e o porto, dividida pela velocidade atual (SOG). É uma estimativa
grosseira — não segue rota de navegação real (contorna costa, evita
terra) nem considera variação de velocidade — mas dá uma referência
muito melhor do que nada, e é a mesma lógica base que qualquer serviço
gratuito de ETA por AIS usa como primeira aproximação.
"""

import math
from dataclasses import dataclass

RAIO_TERRA_KM = 6371.0
NOS_PARA_KMH = 1.852


@dataclass
class EstimativaETA:
    distancia_km: float
    velocidade_nos: float
    horas_estimadas: float
    confiabilidade: str  # 'baixa' (navio devagar/parado) ou 'media' (em navegação)


def distancia_haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    lat1_r, lon1_r, lat2_r, lon2_r = map(math.radians, [lat1, lon1, lat2, lon2])
    dlat = lat2_r - lat1_r
    dlon = lon2_r - lon1_r
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1_r) * math.cos(lat2_r) * math.sin(dlon / 2) ** 2
    c = 2 * math.asin(math.sqrt(a))
    return RAIO_TERRA_KM * c


def calcular_eta(
    navio_lat: float, navio_lon: float, velocidade_nos: float | None,
    porto_lat: float, porto_lon: float,
) -> EstimativaETA | None:
    """Retorna None se não dá pra estimar (navio parado/sem velocidade)."""
    if velocidade_nos is None or velocidade_nos < 1.0:
        return None

    distancia_km = distancia_haversine_km(navio_lat, navio_lon, porto_lat, porto_lon)
    velocidade_kmh = velocidade_nos * NOS_PARA_KMH
    horas = distancia_km / velocidade_kmh

    # confiabilidade simples: velocidade muito baixa (manobrando/fundeado)
    # dá uma estimativa pouco confiável mesmo que não seja zero
    confiabilidade = "media" if velocidade_nos >= 5 else "baixa"

    return EstimativaETA(
        distancia_km=round(distancia_km, 1),
        velocidade_nos=velocidade_nos,
        horas_estimadas=round(horas, 1),
        confiabilidade=confiabilidade,
    )
