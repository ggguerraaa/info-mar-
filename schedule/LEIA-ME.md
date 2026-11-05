# Schedule

`schedule.csv` é o programado. Atualize e faça commit na `main` todo dia: o
push dispara uma rodada do Actions e a tela **Schedule** compara com o AIS.

Separador `;` (ou `,`), datas em horário de Brasília (`dd/mm/aaaa hh:mm`).

| coluna | exemplo | obs |
|---|---|---|
| navio | NAVIO EXEMPLO A | |
| imo | 9000001 | usado para achar o MMSI no cadastro AIS |
| mmsi | 710000001 | opcional; com ele, a 1ª rodada já acha o navio |
| viagem | 001N | |
| porto | Santos | nome, slug (`rio_grande`) ou código (`BRSSZ`) |
| eta / etb / ets | 03/11/2026 06:00 | |
| omitido | sim | vazio = escala mantida |

Porto que o painel não monitora (ex.: Pecém, Buenos Aires) entra em
`portos_extra.json` com nome, latitude e longitude.

## Como o real é detectado

- **Chegada (ATA)**: entrou no raio de fundeio do porto (15 milhas).
- **Atracação (ATB)**: parado (< 0,5 nó) ou "atracado" no AIS, a até 1,5 milha.
- **Saída (ATD)**: saiu do raio do berço ou passou de 3 nós.
- A posição só vale para a escala corrente, na ordem da rota: passar perto de
  um porto que vem depois não conta como chegada.
- **Passou sem sinal**: o navio já está além do porto, a caminho do seguinte,
  e o ETA programado venceu sem chegada vista (falta de antena).
- **Possível omissão**: 24 h depois do ETS programado sem chegada.

## Como o estimado é calculado

- Próximo porto: distância em linha reta × fator de rota ÷ velocidade AIS
  (navio parado: 12 nós de referência).
- Portos seguintes: herdam o atraso da escala anterior (ETS estimado + trânsito
  programado).
- ETB e ETS mantêm a espera e a operação programadas.
- No prazo até ±6 h. Sem fila de porto, maré nem praticagem: é uma primeira
  leitura, não previsão de chegada.
