# Medição do AISstream — 02/11/2026

Script: `ais-service/tools/verificar_ais.py 600` (10 min, ~18h35 de Brasília).
Caixa: lat −56 a 6, lon −73 a −25. **Sem filtro de tipo de mensagem e sem
filtro de navio.**

| Tipo de mensagem | msg/s | Navios distintos | Traz posição |
|---|---:|---:|---|
| PositionReport (Classe A) | 0,48 | 158 | sim |
| ShipStaticData | 0,12 | 65 (65 com nome, 59 com IMO) | não |
| StandardClassBPositionReport | 0,05 | 22 | sim |
| StaticDataReport (Classe B) | 0,04 | 18 (11 com nome) | não |
| **Total** | **0,70** (0,4 KiB/s) | **180 com posição** | |

Mensagens por minuto: 33, 45, 55, 47, 45, 31, 44, 36, 46, 37.

## Decisão

Assinar `PositionReport`, `StandardClassBPositionReport`,
`ExtendedClassBPositionReport` (não apareceu, mas traz posição), `ShipStaticData`
e `StaticDataReport`. A Classe B acrescenta 22 navios (12%) que o filtro antigo
perdia.

## Consequência para a instância gratuita

A carga é pequena: o coletor em produção mediu 0,74 msg/s e 190 navios em
memória nos primeiros 10 min, e 253 navios distintos em ~1 h. Com gravação de
no máximo 1 posição por navio por minuto, o banco cresce na ordem de dezenas de
milhares de linhas por dia. **O limite é a cobertura do AISstream (antenas
terrestres), não a memória.** O coletor continua registrando a taxa no log a
cada 10 min (`Medição AIS: …`) e em `/api/sistema/saude`; reavaliar com os
números das primeiras horas no Render (horário comercial deve ter mais tráfego).
