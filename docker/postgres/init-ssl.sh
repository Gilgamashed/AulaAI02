#!/bin/sh
set -e

CERT_DIR=/var/lib/postgresql/certs
mkdir -p "$CERT_DIR"

if [ ! -f "$CERT_DIR/server.crt" ] || [ ! -f "$CERT_DIR/server.key" ]; then
  openssl req -new -x509 -days 3650 -nodes \
    -out "$CERT_DIR/server.crt" \
    -key "$CERT_DIR/server.key" \
    -subj "/CN=synapseshop-db"
  chown postgres:postgres "$CERT_DIR/server.crt" "$CERT_DIR/server.key" 2>/dev/null || true
  chmod 600 "$CERT_DIR/server.key"
  chmod 644 "$CERT_DIR/server.crt"
fi

# Ensure ssl is configured in postgresql.conf
if [ -n "$PGDATA" ] && [ -f "$PGDATA/postgresql.conf" ]; then
  grep -q "^ssl = on" "$PGDATA/postgresql.conf" || cat >> "$PGDATA/postgresql.conf" <<EOF

# Aula 19 - TLS/SSL
ssl = on
ssl_cert_file = '$CERT_DIR/server.crt'
ssl_key_file = '$CERT_DIR/server.key'
EOF
fi

# Configure pg_hba.conf
if [ -n "$PGDATA" ] && [ -f "$PGDATA/pg_hba.conf" ]; then
  grep -v '^hostssl' "$PGDATA/pg_hba.conf" > "$PGDATA/pg_hba.conf.tmp" 2>/dev/null || true
  mv "$PGDATA/pg_hba.conf.tmp" "$PGDATA/pg_hba.conf"
  {
    echo "hostssl all all 0.0.0.0/0 md5"
    echo "hostssl all all ::/0 md5"
  } >> "$PGDATA/pg_hba.conf"
fi
