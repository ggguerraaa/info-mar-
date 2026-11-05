# Info-Maré

Navios na costa brasileira em tempo real, maré, vento, ondas e condição de
barra dos portos. Open source e de custo zero: só fontes públicas e gratuitas.

> **Auxílio à análise. Não use como única fonte para navegação. A decisão é do
> comandante e da praticagem.**

## O que faz

- **Mapa com todos os navios** que as antenas terrestres do AISstream captam na
  costa (Classe A e B), com nova leitura a cada ~30 min. Cada navio mostra a
  idade da última posição.
- **Buscar e salvar navios** por nome, MMSI ou IMO. "Meus navios" fica no
  navegador de cada pessoa (sem conta), com exportar/importar em JSON.
- **Clicar num porto**: situação, índice operacional (com a conta explicada),
  maré agora e curva do dia, vento e ondas, barra, calado com fonte, navios
  atracados, fundeados e a caminho. Manaus mostra a cota do Rio Negro.
- **Resumo** dos portos escolhidos e **lista de portos**.
- **Frota em destaque**: navios de cabotagem de `ais-service/config/frota.json`
  (Log-In, Aliança, Mercosul Line, Norcoast) com cor por armador, nome no mapa
  e última posição em até 7 dias. O seletor de armador mostra só os navios
  dele e a lista, inclusive os sem sinal.
- **Schedule**: o programado (`schedule/schedule.csv`, commit diário) comparado
  com o real do AIS — ETA, ETB e ETS, chegada/atracação/saída vistas no rastro,
  atraso herdado pelas escalas seguintes, omissão. Qualquer pessoa também pode
  arrastar o CSV de qualquer armador na tela: a análise roda no navegador dela
  e o arquivo não sai do computador.

## Princípios

- **Nada é inventado.** Todo número tem fonte e mostra há quanto tempo foi
  obtido. Sem fonte, aparece "sem dado".
- **Armador não vem do AIS** e nunca é deduzido do nome do navio.
- **Destino e ETA** são digitados pela tripulação; a ETA do AIS não tem ano.
- **Cobertura declarada na tela**: navios longe da costa, com AIS desligado ou
  fora do alcance das antenas não aparecem.

## Arquitetura

Sem servidor. O GitHub Actions roda a cada ~30 min: escuta o AIS por 8 min,
roda os jobs, gera os dados em JSON e publica tudo no GitHub Pages
(guia: [GUIA-DEPLOY.md](GUIA-DEPLOY.md)).

```
.github/workflows/   Rodada do Actions (coleta + build + publicação)
ais-service/         Python: coletor AIS, jobs, gerar_estatico.py (rodada),
                     schedule_status.py (programado x real), backend_app.py (API p/ desenvolvimento)
painel/              Next.js + MapLibre GL, exportação estática; lê /dados/*.json
schedule/            schedule.csv (programado) e portos_extra.json
docs/                Fontes (normas) e medições
```

Banco: SQLite, guardado compactado na branch `dados` entre as rodadas. No
máximo 1 posição por navio por minuto, apagadas após 7 dias.

## Fontes de dados

| Dado | Fonte | Observações |
|---|---|---|
| Posição e dados estáticos dos navios | [AISstream.io](https://aisstream.io) | Antenas terrestres; um coletor por chave. Medição em [docs/medicao-ais-2026-11-02.md](docs/medicao-ais-2026-11-02.md) |
| Bandeira | Tabela MID da [ITU](https://www.itu.int/gladapp/Allocation/MIDs) | 3 primeiros dígitos do MMSI |
| Maré | Tábua DHN/Marinha (previsão astronômica) | Baixada à mão 1x por ano |
| Cota do Rio Negro (Manaus) | Telemetria da ANA, estação 14990000; reserva: Porto de Manaus | |
| Vento e ondas | [Open-Meteo](https://open-meteo.com) (CC BY 4.0) | Cache de 10 min por porto |
| Barra | Praticagens de Santos e Rio Grande | Páginas públicas |
| Calado e limites | Autoridades portuárias e normas | Documento, data e confiança em `ais-service/config/port_operations_config.py` |
| Mapa | [OpenFreeMap](https://openfreemap.org) (Positron), dados © OpenStreetMap | Gratuito, sem chave; URL configurável |

## Rodar localmente

```bash
cd ais-service
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt     # Windows
cp .env.example .env        # preencher AISSTREAM_API_KEY

# Igual ao Actions: escuta, gera painel/out/dados e para
.venv/Scripts/python gerar_estatico.py

# Ou o backend ao vivo para desenvolver o painel
.venv/Scripts/python -m uvicorn backend_app:app --port 8000
cd ../painel && npm install && cp .env.example .env.local && npm run dev   # http://localhost:3000
```

Só um coletor por chave do AISstream: não rode nada local com a chave enquanto
o Actions estiver no meio de uma rodada.

Testes: [TESTES.md](TESTES.md).

## Licença

A definir pelo dono do projeto. Parte da lógica (índice, interpolação de maré,
coeficiente) foi portada do projeto MareAgora, que é **GPL**: a licença
escolhida precisa ser compatível com GPL.
