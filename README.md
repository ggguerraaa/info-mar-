# Info-Maré

Navios na costa brasileira em tempo real, maré, vento, ondas e condição de
barra dos portos. Open source e de custo zero: só fontes públicas e gratuitas.

> **Auxílio à análise. Não use como única fonte para navegação. A decisão é do
> comandante e da praticagem.**

## O que faz

- **Mapa com todos os navios** que as antenas terrestres do AISstream captam na
  costa (Classe A e B), atualizado a cada 12 s. Cada navio mostra a idade da
  última posição.
- **Buscar e salvar navios** por nome, MMSI ou IMO. "Meus navios" fica no
  navegador de cada pessoa (sem conta), com exportar/importar em JSON.
- **Clicar num porto**: situação, índice operacional (com a conta explicada),
  maré agora e curva do dia, vento e ondas, barra, calado com fonte, navios
  atracados, fundeados e a caminho. Manaus mostra a cota do Rio Negro.
- **Resumo** dos portos escolhidos e **lista de portos**.

## Princípios

- **Nada é inventado.** Todo número tem fonte e mostra há quanto tempo foi
  obtido. Sem fonte, aparece "sem dado".
- **Armador não vem do AIS** e nunca é deduzido do nome do navio.
- **Destino e ETA** são digitados pela tripulação; a ETA do AIS não tem ano.
- **Cobertura declarada na tela**: navios longe da costa, com AIS desligado ou
  fora do alcance das antenas não aparecem.

## Arquitetura

Um serviço só (FastAPI) que coleta o AIS, roda os jobs, responde a API e serve
o painel compilado (exportação estática do Next.js).

```
ais-service/   Backend Python: coletor AIS, jobs, API (backend_app.py)
painel/        Frontend Next.js + MapLibre GL (exportação estática em painel/out)
deploy/        Início do serviço e configuração do Litestream
docs/          Fontes (normas) e medições
Dockerfile     Imagem única (painel + backend + Litestream)
render.yaml    Blueprint do Render
```

Banco: SQLite, em WAL, com backup contínuo pelo Litestream. A última posição
de cada navio fica em memória; no banco, no máximo 1 posição por navio por
minuto, apagadas após 7 dias.

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
.venv/Scripts/python -m uvicorn backend_app:app --port 8000

cd ../painel
npm install
npm run build               # gera painel/out; o backend passa a servir em http://localhost:8000
# ou, para desenvolver: cp .env.example .env.local && npm run dev  (http://localhost:3000)
```

Só um coletor por chave do AISstream: não rode o backend local enquanto o do
Render estiver no ar com a mesma chave.

Deploy: [GUIA-DEPLOY.md](GUIA-DEPLOY.md). Testes: [TESTES.md](TESTES.md).

## Licença

A definir pelo dono do projeto. Parte da lógica (índice, interpolação de maré,
coeficiente) foi portada do projeto MareAgora, que é **GPL**: a licença
escolhida precisa ser compatível com GPL.
