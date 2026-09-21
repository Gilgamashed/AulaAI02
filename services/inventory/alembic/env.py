"""Ambiente de migração do Alembic para o microsserviço inventory.

O Alembic governa SOMENTE as tabelas do FastAPI (metadata do inventory). O
filtro `include_object` impede que o autogenerate/check enxergue as tabelas do
Django (auth_user, core_*, ...), que pertencem ao versionamento próprio do
Django. É isso que evita o conflito entre os dois sistemas de migração no mesmo
PostgreSQL (decisão da Aula 6).
"""

from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context

# `import app.models` registra o InventoryItem no metadata da Base declarativa.
from app import models  # noqa: F401
from app.config import get_sqlalchemy_url
from app.database import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

config.set_section_option(config.config_ini_section, "sqlalchemy.url", get_sqlalchemy_url())

target_metadata = Base.metadata


def include_object(obj, name: str, type_: str, reflected: bool, compare_to) -> bool:
    """Restringe o autogenerate às tabelas do próprio microserviço.

    Tabelas fora do metadata do inventory (caso do Django) são ignoradas — e
    seus filhos (colunas, índices, constraints) também herdam o filtro via a
    tabela dona (atributo `.table`).
    """
    if type_ == "table":
        return name in target_metadata.tables
    table = getattr(obj, "table", None)
    return table is not None and table.name in target_metadata.tables


def run_migrations_offline() -> None:
    """Executa as migrações sem conexão, emitindo apenas o SQL."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_object=include_object,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Executa as migrações com conexão ao banco (uso padrão do compose)."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_object=include_object,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
