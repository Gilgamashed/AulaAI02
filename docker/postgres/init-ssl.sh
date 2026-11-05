#!/bin/sh
# Garante TLS no PostgreSQL em QUALQUER start do container.
#
# Roda em dois momentos:
#   1. pelo wrapper de entrypoint (docker-entrypoint-wrapper.sh), quando o
#      volume `pgdata` JÁ foi inicializado — nesse caso o Postgres não executa
#      /docker-entrypoint-initdb.d de novo;
#   2. por /docker-entrypoint-initdb.d no primeiro start, depois do initdb.
#
# Por que os certificados ficam DENTRO do PGDATA: diretório fora do volume é
# apagado quando o container é recriado (`docker compose up` que troca a
# imagem), e o postgresql.conf persistido passaria a apontar para arquivos
# inexistentes — o servidor não sobe. Guardando em $PGDATA/certs, certificado
# e banco sobrevivem juntos.
set -eu

PGDATA="${PGDATA:-/var/lib/postgresql/data}"
CERT_DIR="$PGDATA/certs"

mkdir -p "$CERT_DIR"

# `-newkey` + `-keyout` geram a chave; `-key` sozinho tentaria LER uma chave
# existente e falharia no primeiro start, quando o diretório ainda está vazio.
# `-nodes` dispensa passphrase para o servidor subir sem interação (a chave é
# protegida por permissão 600).
if [ ! -s "$CERT_DIR/server.crt" ] || [ ! -s "$CERT_DIR/server.key" ]; then
  openssl req -x509 -newkey rsa:2048 -nodes -days 3650 \
    -keyout "$CERT_DIR/server.key" \
    -out "$CERT_DIR/server.crt" \
    -subj "/CN=synapseshop-db"
fi

# No wrapper o processo é root; no initdb.d, postgres. Só o root precisa (e
# consegue) ajustar dono.
if [ "$(id -u)" = "0" ]; then
  chown -R postgres:postgres "$CERT_DIR"
fi
chmod 600 "$CERT_DIR/server.key"
chmod 644 "$CERT_DIR/server.crt"

# Reescreve o bloco TLS em vez de só anexar: volumes criados por versões
# anteriores apontavam para /var/lib/postgresql/certs (fora do volume), e
# manter a linha antiga faria o servidor falhar ao abrir a chave.
CONF="$PGDATA/postgresql.conf"
if [ -f "$CONF" ]; then
  grep -v -e '^# Aula 19 - TLS/SSL$' \
    -e '^ssl = on$' \
    -e '^ssl_cert_file = ' \
    -e '^ssl_key_file = ' "$CONF" > "$CONF.tmp" || true
  if [ -s "$CONF.tmp" ]; then
    mv "$CONF.tmp" "$CONF"
  else
    rm -f "$CONF.tmp"
  fi

  cat >> "$CONF" <<EOF

# Aula 19 - TLS/SSL
ssl = on
ssl_cert_file = '$CERT_DIR/server.crt'
ssl_key_file = '$CERT_DIR/server.key'
EOF
fi

HBA="$PGDATA/pg_hba.conf"
if [ -f "$HBA" ]; then
  grep -v '^hostssl' "$HBA" > "$HBA.tmp" || true
  if [ -s "$HBA.tmp" ]; then
    mv "$HBA.tmp" "$HBA"
  else
    rm -f "$HBA.tmp"
  fi

  {
    echo "hostssl all all 0.0.0.0/0 md5"
    echo "hostssl all all ::/0 md5"
  } >> "$HBA"
fi
