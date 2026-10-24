FROM postgres:16-alpine

ENV PGDATA=/var/lib/postgresql/data

RUN apk add --no-cache openssl

COPY init-ssl.sh /docker-entrypoint-initdb.d/init-ssl.sh
RUN chmod +x /docker-entrypoint-initdb.d/init-ssl.sh

EXPOSE 5432
