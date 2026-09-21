# Diretório de versões do Alembic do microserviço inventory.

# Cada arquivo aqui é uma migração versionada. A revisão atual fica registrada
# na tabela `alembic_version` do PostgreSQL compartilhado com o Django.
#
# Comandos úteis (rodar no container, via docker compose):
#   alembic upgrade head   # aplica todas as migrações pendentes
#   alembic current        # mostra a versão aplicada
#   alembic history        # mostra o histórico de revisões
#   alembic downgrade -1   # rollback seguro de uma revisão
#   alembic check          # valida se o schema está em dia com os models