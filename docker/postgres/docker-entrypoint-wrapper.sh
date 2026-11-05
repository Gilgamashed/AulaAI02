#!/bin/sh
# Wrapper do entrypoint oficial da imagem postgres.
#
# O entrypoint oficial só executa /docker-entrypoint-initdb.d na PRIMEIRA
# inicialização do volume. Como os certificados TLS vivem dentro do PGDATA
# (para sobreviver à recriação do container), um volume já inicializado por
# uma versão anterior — ou que perdeu os arquivos de certificado — subiria com
# `ssl = on` apontando para chave inexistente e morreria no startup. Este
# wrapper garante TLS antes de delegar ao entrypoint oficial, em todo start.
set -eu

PGDATA="${PGDATA:-/var/lib/postgresql/data}"

if [ -f "$PGDATA/PG_VERSION" ]; then
  /usr/local/bin/ensure-ssl.sh
fi

exec /usr/local/bin/docker-entrypoint.sh "$@"
