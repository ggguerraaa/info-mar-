# Guia de deploy — Info-Maré no Render

Um serviço web gratuito no Render (Docker) com API + painel na mesma URL, banco
SQLite com backup contínuo pelo Litestream e um pinger externo para o serviço
não dormir.

Conferido em 02/11/2026 (confira de novo, isso muda):
- **Render, plano gratuito**: 750 horas por mês por workspace (dá um serviço
  24 h); dorme após 15 min sem tráfego de entrada e leva ~1 min para acordar;
  disco apagado a cada reinício, deploy ou sono. A página do plano não exige
  cartão para o gratuito; sem cartão, o serviço é suspenso se estourar banda ou
  minutos de build. RAM do plano gratuito: confira na tela de criação.
- **Cloudflare R2, gratuito**: 10 GB, 1 milhão de operações classe A e 10
  milhões classe B por mês, sem custo de saída. A página de preços **não diz se
  exige cartão**: confira no cadastro antes de criar a conta. Alternativa:
  Backblaze B2 (também com 10 GB gratuitos; confira os termos).
- **OpenFreeMap**: gratuito, sem chave, sem limite declarado, uso comercial
  permitido; atribuição obrigatória (o MapLibre já mostra).

## 1. Antes de publicar o repositório

1. **Troque a chave do AISstream.** Esta pasta não tinha git, então não há
   histórico local para varrer — mas se o código já esteve em algum repositório
   (GitHub, outra máquina), trate a chave como vazada. Gere uma nova no site do
   AISstream e use só a nova no Render.
2. O repositório novo tem um único commit, varrido com o gitleaks 8.30.1
   (nenhum segredo). Rode de novo antes de cada publicação:
   `gitleaks git --no-banner -v .`
3. `.env` reais ficam fora (`.gitignore`); só os `.env.example` entram.
4. Termos de uso: AISstream, páginas das praticagens e do Porto de Manaus
   ainda não foram conferidos. Se algum proibir, desligue a fonte (o painel
   mostra "sem dado").

## 2. Armazenamento para o Litestream (R2)

1. Crie um bucket (ex.: `info-mare-backup`) e um token de API com permissão
   de leitura e escrita **só nesse bucket**.
2. Anote: endpoint S3 (`https://<conta>.r2.cloudflarestorage.com`), Access Key
   ID e Secret Access Key.

## 3. Render

1. Publique o repositório no GitHub (público).
2. No Render: **New → Blueprint** → escolha o repositório. Ele lê o
   `render.yaml` e pede os valores marcados como segredo:
   - `AISSTREAM_API_KEY` (a chave nova)
   - `LITESTREAM_BUCKET`, `LITESTREAM_ENDPOINT`,
     `LITESTREAM_ACCESS_KEY_ID`, `LITESTREAM_SECRET_ACCESS_KEY`
3. O build compila o painel e o backend numa imagem só. Ao subir, o serviço:
   restaura o banco do R2 (se houver), começa a replicar a cada 10 s e conecta
   ao AISstream.
4. Teste: `https://<serviço>.onrender.com/health` responde
   `{"status":"ok","ais_conectado":true}` em até 1 min.

**Um coletor por chave.** Em cada deploy o Render sobe a instância nova antes
de desligar a antiga; a nova pode receber 429 do AISstream por alguns segundos.
O coletor espera 1 min e tenta de novo (espera crescente até 5 min). Não rode o
backend local com a mesma chave ao mesmo tempo.

## 4. Pinger (o serviço não pode dormir: dormindo, o AIS para)

UptimeRobot ou cron-job.org (gratuitos): monitor HTTP em
`https://<serviço>.onrender.com/health` a cada **5 min**. O `/health` é leve e
não conta no limite de requisições. Mesmo assim pode haver lacunas: os
períodos de coleta ficam em `/api/sistema/coleta-ais`.

## 5. Primeiras horas: medir

O log do Render mostra a cada 10 min uma linha `Medição AIS:` com mensagens
por segundo, navios em memória, memória do processo (RSS) e tamanho do banco.
`/api/sistema/saude` mostra o mesmo. Se a memória chegar perto do limite da
instância: reduza a caixa (`AIS_CAIXAS`) ou aumente
`AIS_INTERVALO_GRAVACAO_S`. A medição local de 02/11/2026 deu 0,7 msg/s e ~250
navios por hora — folga grande.

## 6. Teste de reinício

1. Salve um navio em "Meus navios" e anote o rastro de 24 h dele.
2. No Render: **Manual Deploy → Restart service**.
3. Ao voltar: o mapa já mostra os navios (memória refeita do banco
   restaurado), o card do navio mostra o rastro anterior e a busca acha os
   navios já vistos.

Testado localmente (sem R2): após derrubar o processo, 253 de 253 navios
voltaram para a memória e o rastro ficou intacto. **O caminho com Litestream
não foi testado nesta máquina (sem Docker)**: faça este teste no primeiro deploy.

## 7. Tábua de maré anual

Uma vez por ano, quando a DHN publicar a tábua do ano seguinte, baixe os PDFs à
mão (o site bloqueia robôs) e atualize `ais-service/data/mare/`.
