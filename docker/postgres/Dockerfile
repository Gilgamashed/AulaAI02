FROM postgres:16-alpine

ENV PGDATA=/var/lib/postgresql/data

RUN apk add --no-cache openssl

# Mesmo script em dois pontos:
#   - /docker-entrypoint-initdb.d: primeira inicialização do volume;
#   - /usr/local/bin/ensure-ssl.sh: chamado pelo wrapper em todo start de um
#     volume já inicializado, onde o initdb.d não é executado.
COPY init-ssl.sh /docker-entrypoint-initdb.d/init-ssl.sh
COPY init-ssl.sh /usr/local/bin/ensure-ssl.sh
COPY docker-entrypoint-wrapper.sh /usr/local/bin/docker-entrypoint-wrapper.sh
RUN chmod +x /docker-entrypoint-initdb.d/init-ssl.sh \
    /usr/local/bin/ensure-ssl.sh \
    /usr/local/bin/docker-entrypoint-wrapper.sh

ENTRYPOINT ["/usr/local/bin/docker-entrypoint-wrapper.sh"]
# Definir ENTRYPOINT zera o CMD herdado da imagem base; sem esta linha o
# entrypoint oficial recebe zero argumentos e o container sai com código 0.
CMD ["postgres"]

EXPOSE 5432
