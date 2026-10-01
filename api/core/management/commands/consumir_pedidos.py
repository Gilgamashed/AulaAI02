"""`manage.py consumir_pedidos` — o *worker* do evento `PedidoCriado`.

O comando existe para que o consumidor seja um **processo** do mesmo projeto
Django (mesmos models, mesmas migrations, mesmo código de domínio), e não um
microsserviço que teria de duplicar a modelagem de Pedido em um segundo ORM.
No compose ele roda no serviço `worker`, com a mesma imagem da API — só o
comando de entrada muda.
"""

from django.core.management.base import BaseCommand

from core.messaging.consumidor import Consumidor


class Command(BaseCommand):
    help = (
        "Consome a fila de pedidos criados, aplica o estado do pedido com "
        "idempotência e encaminha falhas repetidas para a DLQ."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--fila",
            default=None,
            help=(
                "Fila a consumir (padrão: PEDIDO_FILA das settings, "
                "'pedidos.criados'). Útil para reprocessar a DLQ em ambiente "
                "de teste."
            ),
        )
        parser.add_argument(
            "--max-mensagens",
            type=int,
            default=None,
            help=(
                "Processa no máximo N mensagens e encerra. Sem este argumento "
                "o worker consome continuamente, como um serviço."
            ),
        )

    def handle(self, *args, **options) -> None:
        consumidor = Consumidor(
            fila=options["fila"],
            max_mensagens=options["max_mensagens"],
        )
        # O log estruturado (logger "core.messaging") é a saída de referência;
        # esta linha serve para quem está no terminal sem `docker compose logs`.
        self.stdout.write(
            f"worker consumindo a fila '{consumidor.fila}' "
            f"(máx. {options['max_mensagens'] or 'ilimitado'} mensagens)"
        )
        consumidor.rodar()
