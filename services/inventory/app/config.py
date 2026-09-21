"""Configuração do microsserviço inventory — leitura central de ambiente."""

import os

# URL do PostgreSQL fornecida pelo docker-compose (mesmo formato do Django).
# O inventory usa a MESMA base de dados do Django, mas é dono apenas das
# próprias tabelas (governança de migração via Alembic).
DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://synapse:synapse@localhost:5432/synapse",
)


def get_sqlalchemy_url() -> str:
    """Adapta a URL para o dialeto do psycopg 3 usado pelo SQLAlchemy.

    O Django entende o esquema `postgresql://`, mas o SQLAlchemy o mapeia por
    padrão para o driver psycopg2. Como o projeto usa psycopg 3, trocamos o
    esquema para `postgresql+psycopg://`.
    """
    url = DATABASE_URL
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url
