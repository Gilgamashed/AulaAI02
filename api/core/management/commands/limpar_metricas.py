"""Poda o log de métricas de requisição (Aula 20).

A tabela `core_requisicao_metrica` recebe uma linha por requisição da API.
Sem poda, ela cresce indefinidamente e o dashboard passa a varrer um volume
que não cabe na janela de consulta. Este comando mantém os últimos N dias
(padrão: 30) e pode ser agendado no host (cron/Task Scheduler).

Uso:
    docker compose exec api python api/manage.py limpar_metricas
    docker compose exec api python api/manage.py limpar_metricas --dias 7
    docker compose exec api python api/manage.py limpar_metricas --dias 7 --dry-run
"""

from __future__ import annotations

from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from core.models import RequisicaoMetrica


class Command(BaseCommand):
    help = "Remove métricas de requisição mais antigas que o período de retenção."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--dias",
            type=int,
            default=30,
            help="Dias de retenção (padrão: 30; use 0 para remover tudo).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Apenas informa quantas linhas seriam removidas.",
        )

    def handle(self, *args, **options) -> None:
        dias = options["dias"]
        if dias < 0:
            raise CommandError("--dias deve ser maior ou igual a zero.")

        corte = timezone.now() - timedelta(days=dias)
        consulta = RequisicaoMetrica.objects.filter(created_at__lt=corte)
        total = consulta.count()

        if options["dry_run"]:
            self.stdout.write(
                f"[dry-run] {total} métrica(s) anterior(es) a {corte.isoformat()} seriam removidas."
            )
            return

        removidas, _ = consulta.delete()
        self.stdout.write(
            self.style.SUCCESS(
                f"{removidas} métrica(s) removida(s); retenção de {dias} dia(s) "
                f"(corte em {corte.isoformat()})."
            )
        )
