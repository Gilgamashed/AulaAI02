# Data migration que cria o índice essencial da coluna `email` do `auth_user`.
#
# O `django.contrib.auth` não indexa o email (coluna de acesso comum do modelo
# User). Como o app de origem é de terceiros (contrib), o índice é criado aqui,
# no app `core` — preservando a governança: TODAS as tabelas do Django seguem
# geridas pelo Django (esta migração roda via `manage.py migrate`), e o Alembic
# continua restrito às tabelas do FastAPI (inventory).
#
# Rollback seguro: `reverse_sql` remove o índice se a migração for revertida.

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0002_alter_item_created_at_desc_index"),
        # Garante que a tabela `auth_user` já exista antes do CREATE INDEX.
        ("auth", "0012_alter_user_first_name_max_length"),
    ]

    operations = [
        migrations.RunSQL(
            sql="CREATE INDEX IF NOT EXISTS auth_user_email_idx ON auth_user (email);",
            reverse_sql="DROP INDEX IF EXISTS auth_user_email_idx;",
        ),
    ]