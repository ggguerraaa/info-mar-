"""
Nascer/pôr do sol — porta de getSunTimes() em lib/portOperations.ts do
fork MareAgora (GPL, só a lógica foi portada, código escrito do zero).
Algoritmo padrão de almanaque náutico (Sunrise/Sunset Algorithm).
"""

import math


def _formatar_hora(h: float) -> str:
    hh = int(h)
    mm = round((h - hh) * 60)
    if mm == 60:
        hh += 1
        mm = 0
    return f"{hh:02d}:{mm:02d}"


def _calcular(is_rise: bool, n: float, lng_hour: float, lat: float, lon: float, utc_offset: float) -> str:
    t = n + ((6 if is_rise else 18) - lng_hour) / 24
    m = 0.9856 * t - 3.289
    l = m + 1.916 * math.sin(math.radians(m)) + 0.02 * math.sin(math.radians(2 * m)) + 282.634
    l = l % 360
    ra = math.degrees(math.atan(0.91764 * math.tan(math.radians(l))))
    lq = math.floor(l / 90) * 90
    raq = math.floor(ra / 90) * 90
    ra = (ra + (lq - raq)) / 15
    sin_dec = 0.39782 * math.sin(math.radians(l))
    cos_dec = math.cos(math.asin(sin_dec))
    cos_h = (math.cos(math.radians(90.833)) - sin_dec * math.sin(math.radians(lat))) / (
        cos_dec * math.cos(math.radians(lat))
    )
    if cos_h > 1 or cos_h < -1:
        return "--:--"
    h = (360 - math.degrees(math.acos(cos_h))) / 15 if is_rise else math.degrees(math.acos(cos_h)) / 15
    t_local = h + ra - 0.06571 * t - 6.622
    ut = (t_local - lng_hour) % 24
    local = (ut + utc_offset) % 24
    return _formatar_hora(local)


def nascer_por_do_sol(ano: int, mes: int, dia: int, lat: float, lon: float, utc_offset: float = -3) -> dict:
    n1 = math.floor(275 * mes / 9)
    n2 = math.floor((mes + 9) / 12)
    n3 = 1 + math.floor((ano - 4 * math.floor(ano / 4) + 2) / 3)
    n = n1 - n2 * n3 + dia - 30
    lng_hour = lon / 15

    return {
        "nascer": _calcular(True, n, lng_hour, lat, lon, utc_offset),
        "por": _calcular(False, n, lng_hour, lat, lon, utc_offset),
    }
