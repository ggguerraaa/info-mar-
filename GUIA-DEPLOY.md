# Guia de deploy — Info-Maré no GitHub (sem servidor)

Tudo roda no GitHub, de graça em repositório público:

- **GitHub Actions** (`.github/workflows/atualizar.yml`) liga uma máquina a
  cada ~30 min, escuta o AISstream por 8 min, roda os jobs (praticagem, índice
  operacional, alertas), compara o schedule e gera os dados em JSON.
- **GitHub Pages** publica o painel (exportação estática do Next) junto com
  esses JSON. Quem abre o link vê a última rodada.
- **Branch `dados`** guarda o banco SQLite compactado entre uma rodada e a
  outra (posições dos últimos 7 dias, cadastro dos navios, eventos do
  schedule), sempre com um único commit, sem sujar o histórico da `main`.

Conferido em 05/11/2026 (confira de novo, isso muda): Actions e Pages são
gratuitos e sem limite de minutos em repositório **público**; em repositório
privado o plano Free dá 2.000 min/mês, e cada rodada gasta ~11 min (não cabe).

## O que muda em relação ao Render

| | Render (antes) | GitHub (agora) |
|---|---|---|
| Mapa | ao vivo, atualiza a cada 12 s | foto da última rodada (até ~30 min) |
| Coleta AIS | 24 h | 8 min a cada 30 min (~27% do tempo) |
| Rastro | 1 ponto/min contínuo | 1 ponto/min dentro das janelas de escuta |
| Servidor, pinger, Litestream, R2 | precisava | nada |

O cron do Actions pode atrasar alguns minutos em horário de pico.

## 1. Desligue o Render (obrigatório)

O AISstream aceita **uma conexão por chave**. Com o Render ligado, ele e o
Actions se derrubam. No Render: **Settings → Suspend service** (ou apague o
serviço). O `render.yaml`, o `Dockerfile` e `deploy/` continuam no repositório
só para quem quiser rodar com Docker; o Render não é mais usado.

## 2. Configurar o GitHub (uma vez)

1. **Settings → Secrets and variables → Actions → New repository secret**:
   `AISSTREAM_API_KEY` = a chave do aisstream.io. Se a chave já esteve em algum
   lugar público, gere uma nova antes.
2. **Settings → Pages → Build and deployment → Source: GitHub Actions**.
3. Repositório público (senão os minutos acabam).
4. **Actions → Atualizar Info-Maré → Run workflow** para a primeira rodada. O
   link do site sai no resumo da execução:
   `https://<usuario>.github.io/<repositorio>/`.

Rodadas de `push` (schedule novo, código novo) escutam o AIS só 1,5 min, para
publicar rápido; as agendadas escutam 8 min.

## 3. Rotina: schedule diário

Atualize `schedule/schedule.csv` e faça commit na `main` (pelo VS Code ou pelo
botão de lápis do próprio GitHub). O push dispara uma rodada; a tela
**Schedule** do painel mostra programado x real. Formato em
[schedule/LEIA-ME.md](schedule/LEIA-ME.md).

## 4. Conferir uma rodada

Na aba **Actions**, cada execução mostra no log:
- `AIS: N navios com posição...` (com a chave certa, N > 0)
- uma linha por fonte (`praticagem: ok`, `painel santos: ok`...). Fonte que
  falhou aparece como `FALHOU` e o painel mostra "sem dado" naquele bloco.
- `Guardar o banco na branch "dados"` com o tamanho do arquivo.

Fontes que ainda não foram testadas a partir das máquinas do GitHub (EUA):
sites das praticagens, Porto de Manaus e ANA. Se alguma bloquear IP de fora do
Brasil, o bloco correspondente fica "sem dado".

## 5. Rodar localmente

```powershell
cd ais-service
.\.venv\Scripts\python.exe gerar_estatico.py          # escuta 8 min e gera painel\out\dados
$env:ESCUTA_SEGUNDOS=0; .\.venv\Scripts\python.exe gerar_estatico.py   # só gera, sem AIS
```

Não rode com a chave enquanto o Actions estiver no meio de uma rodada.

## 6. Tábua de maré anual

Uma vez por ano, quando a DHN publicar a tábua do ano seguinte, baixe os PDFs à
mão (o site bloqueia robôs) e atualize `ais-service/data/mare/`.
