"""Configuração do microsserviço inventory — leitura central de ambiente."""

import os
from urllib.parse import quote_plus

SSL_MODES_PERMITIDOS = {"require", "verify-ca", "verify-full", "disable", "allow", "prefer"}


def _normalizar_sslmode() -> str:
    sslmode = os.environ.get("DB_SSLMODE", "require").strip().lower() or "require"
    if sslmode not in SSL_MODES_PERMITIDOS:
        return "require"
    return sslmode


def get_database_url() -> str:
    # Prioriza variáveis DB_* (Aula 19) com fallback para DATABASE_URL
    if os.environ.get("DB_HOST"):
        host = os.environ["DB_HOST"]
        port = os.environ.get("DB_PORT", "5432")
        dbname = os.environ["DB_NAME"]
        user = os.environ["DB_USER"]
        password = os.environ["DB_PASSWORD"]
        sslmode = _normalizar_sslmode()
        return f"postgresql://{quote_plus(user)}:{quote_plus(password)}@{host}:{port}/{dbname}?sslmode={sslmode}"
    url = os.environ.get(
        "DATABASE_URL",
        "postgresql://synapse:synapse@localhost:5432/synapse",
    )
    return url


# Mantém compatibilidade
DATABASE_URL = get_database_url()


def get_sqlalchemy_url() -> str:
    """Adapta a URL para o dialeto do psycopg 3 usado pelo SQLAlchemy."""
    url = get_database_url()
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg://", 1)
    if url.startswith("postgresql+psycopg2://"):
        return url.replace("postgresql+psycopg2://", "postgresql+psycopg://", 1)
    return url
