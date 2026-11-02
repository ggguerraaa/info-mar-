#!/bin/sh
# Início do serviço. Com o Litestream configurado (LITESTREAM_BUCKET), o banco
# é restaurado do armazenamento antes de subir e replicado continuamente —
# o disco do plano gratuito do Render é apagado a cada reinício.
set -e
mkdir -p "$(dirname "$DB_PATH")"
PORTA="${PORT:-8000}"

if [ -n "$LITESTREAM_BUCKET" ]; then
  litestream restore -if-db-not-exists -if-replica-exists -config /etc/litestream.yml "$DB_PATH"
  # -exec: o Litestream repassa o SIGTERM ao uvicorn, que fecha o WebSocket do
  # AISstream antes de sair (só um coletor por chave).
  exec litestream replicate -config /etc/litestream.yml \
    -exec "uvicorn backend_app:app --host 0.0.0.0 --port $PORTA --timeout-graceful-shutdown 15"
fi

echo "LITESTREAM_BUCKET vazio: rodando sem backup (o banco some ao reiniciar)."
exec uvicorn backend_app:app --host 0.0.0.0 --port "$PORTA" --timeout-graceful-shutdown 15
