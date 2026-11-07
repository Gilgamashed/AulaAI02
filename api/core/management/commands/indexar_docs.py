"""Comando `manage.py indexar_docs` (Aula 24).

Constrói o índice SQLite do assistente de documentação a partir de
`README.md` e `docs/openapi.yaml` (ou das fontes passadas em `--source`).

Exemplos:

    python api/manage.py indexar_docs
    python api/manage.py indexar_docs --force
    python api/manage.py indexar_docs --source README.md --source docs/aulas/24-rag-documentacao.md
"""

from __future__ import annotations

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from core.ask_docs.erros import AskDocsErro
from core.ask_docs.indice import IndiceRag
from core.ask_docs.ingestao import indexar


class Command(BaseCommand):
    help = "Reindexa a documentação usada pelo assistente RAG (/ask_docs/)."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--force",
            action="store_true",
            help="Reconstrói o índice mesmo que os hashes não tenham mudado.",
        )
        parser.add_argument(
            "--root",
            default=None,
            help="Raiz do projeto usada para resolver as fontes.",
        )
        parser.add_argument(
            "--index-path",
            default=None,
            help="Caminho do arquivo SQLite do índice.",
        )
        parser.add_argument(
            "--source",
            action="append",
            default=None,
            help="Fonte relativa à raiz (pode ser repetida).",
        )

    def handle(self, *args, **options) -> None:
        try:
            indice = IndiceRag(options["index_path"]) if options["index_path"] else None
            resultado = indexar(
                raiz=Path(options["root"]) if options["root"] else None,
                fontes=options["source"],
                forcar=bool(options["force"]),
                indice=indice,
            )
        except AskDocsErro as falha:
            raise CommandError(str(falha)) from falha

        if not resultado.reindexado:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Índice já atualizado: {resultado.chunks} chunks."
                )
            )
            return

        for documento in resultado.documentos:
            self.stdout.write(
                f"  {documento.path} ({documento.title}): "
                f"{documento.chunks} chunks"
            )
        self.stdout.write(
            self.style.SUCCESS(
                f"Índice reconstruído: {resultado.chunks} chunks em "
                f"{len(resultado.documentos)} documento(s)."
            )
        )
