"""Camada de conexão do inventory (SQLAlchemy 2.0).

Centraliza o engine e a fábrica de sessões. `Base` é a base declarativa cujo
`metadata` alimenta o Alembic.
"""

import os

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import get_sqlalchemy_url


def _get_int(nome: str, padrao: int) -> int:
    try:
        return int(os.environ.get(nome, str(padrao)).strip())
    except (TypeError, ValueError):
        return padrao


def _montar_connect_args() -> dict:
    connect_args_dict: dict = {
        "connect_timeout": _get_int("DB_CONNECT_TIMEOUT", 10),
    }
    timeout_ms = _get_int("DB_STATEMENT_TIMEOUT_MS", 30000)
    connect_args_dict["options"] = f"-c statement_timeout={timeout_ms}"
    return connect_args_dict


engine = create_engine(
    get_sqlalchemy_url(),
    pool_size=_get_int("DB_POOL_SIZE", 10),
    max_overflow=_get_int("DB_MAX_OVERFLOW", 20),
    pool_timeout=_get_int("DB_POOL_TIMEOUT", 30),
    pool_recycle=_get_int("DB_POOL_RECYCLE", 1800),
    pool_pre_ping=True,
    connect_args=_montar_connect_args(),
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    """Base declarativa do microserviço."""

