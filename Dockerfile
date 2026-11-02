# Um serviço só: o painel (exportação estática do Next) é compilado aqui e
# servido pelo backend FastAPI na mesma URL. Usado pelo Render (render.yaml)
# e por quem quiser rodar com Docker.

FROM node:22-slim AS painel
WORKDIR /painel
COPY painel/package.json painel/package-lock.json ./
RUN npm ci
COPY painel/ ./
# vazio = o navegador chama /api na mesma origem
ENV NEXT_PUBLIC_BACKEND_URL=""
RUN npm run build

FROM python:3.12-slim
ARG LITESTREAM_VERSION=0.3.13
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates wget \
 && wget -q "https://github.com/benbjohnson/litestream/releases/download/v${LITESTREAM_VERSION}/litestream-v${LITESTREAM_VERSION}-linux-amd64.deb" \
 && dpkg -i litestream-*.deb && rm litestream-*.deb \
 && apt-get purge -y wget && rm -rf /var/lib/apt/lists/*

WORKDIR /app/ais-service
COPY ais-service/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY ais-service/ .
COPY --from=painel /painel/out /app/painel/out
COPY deploy/litestream.yml /etc/litestream.yml
COPY deploy/iniciar.sh /app/iniciar.sh

# Banco fora da pasta do código (data/mare/ guarda as tábuas, que vão na imagem)
ENV PAINEL_DIR=/app/painel/out \
    DB_PATH=/app/dados/tabua_mare.db \
    PYTHONUNBUFFERED=1

EXPOSE 8000
CMD ["sh", "/app/iniciar.sh"]
