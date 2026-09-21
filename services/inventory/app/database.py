"""Camada de conexão do inventory (SQLAlchemy 2.0).

Centraliza o engine e a fábrica de sessões. `Base` é a base declarativa cujo
`metadata` alimenta o Alembic — portanto as tabelas registradas aqui são
exatamente as que o Alembic governa.
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import get_sqlalchemy_url

# Engine único do serviço. `pool_pre_ping` valida a conexão antes de usar,
# evitando erros com conexões ociosas ao PostgreSQL.
engine = create_engine(get_sqlalchemy_url(), pool_pre_ping=True)

# Fábrica de sessões usada pelas dependências do FastAPI (uma sessão por
# requisição) e pelo script de medição de transações.
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    """Base declarativa do microserviço — origem do `metadata` do Alembic."""
