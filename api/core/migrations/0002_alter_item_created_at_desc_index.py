# Migração escrita manualmente (paridade com o que o makemigrations geraria).
# Índice essencial da listagem padrão do Item: `ORDER BY -created_at` usado
# pelo ItemViewSet (API) e pelo Admin — sem índice de suporte, o PostgreSQL
# faria seq-scan + sort conforme o catálogo cresce.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0001_initial"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="item",
            index=models.Index(
                fields=["-created_at"],
                name="core_item_created_at_desc_idx",
            ),
        ),
    ]