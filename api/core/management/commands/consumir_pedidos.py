"""`manage.py consumir_pedidos` — o *worker* dos eventos de pedido e pagamento.

O comando existe para que o consumidor seja um **processo** do mesmo projeto
Django (mesmos models, mesmas migrations, mesmo código de domínio), e não um
microsserviço que teria de duplicar a modelagem em um segundo ORM. No compose ele
roda nos serviços `worker-kafka` (fluxo `pedidos`), `worker-pagamentos` (fluxo
`pagamentos`) e `worker` (RabbitMQ, profile `rabbitmq`) — mesma imagem, mesmo
comando, e só a variável `MENSAGERIA_BROKER` e o `--fluxo` diferentes. Essa
simetria é proposital: é o que prova que a seleção de transporte acontece num
único lugar (`core.messaging.broker`) e não espalhada pela view, pelo worker e
pelo comando de recuperação.

O `Consumer` do Kafka sobe junto a **duas** rotinas: o consumidor do tópico
principal e o *replayer* dos tópicos de retry (que reconstrói o atraso de
5/15/45 s, já que o Kafka não tem TTL por mensagem). Ver
`core.messaging.kafka_consumidor` e `core.messaging.kafka_replayer`.

Por que `--fluxo` e não dois comandos
(`consumir_pedidos` e `consumir_pagamentos`): os dois workers rodam **exatamente
o mesmo código** — mesma escada de reentrega, mesmo commit manual, mesma DLQ,
mesmo replayer. Um comando por fluxo duplicaria esse arquivo inteiro e criaria
o problema oposto ao que o `--fluxo` resolve (dois comandos que divergem). O que
realmente muda entre os dois está no argumento.
"""

from core.messaging import broker as mensageria
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = (
        "Consome o tópico/fila de um fluxo (pedidos ou pagamentos), aplica o "
        "efeito do evento com idempotência e encaminha falhas repetidas para a "
        "DLQ do fluxo. O broker é escolhido por MENSAGERIA_BROKER "
        "(padrão: kafka); no RabbitMQ só existe o fluxo 'pedidos'."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--fluxo",
            choices=mensageria.FLUXOS,
            default=mensageria.FLUXO_PEDIDOS,
            help=(
                "Fluxo de evento a consumir: 'pedidos' (evento PedidoCriado, "
                "Aulas 9/10) ou 'pagamentos' (evento PagamentoRegistrado, Aula "
                "11). Tópico, group.id, DLQ e nomes dos logs saem daqui. Só "
                "funciona no Kafka."
            ),
        )
        parser.add_argument(
            "--destino",
            default=None,
            help=(
                "Fila (RabbitMQ, padrão: PEDIDO_FILA das settings, "
                "'pedidos.criados') ou tópico (Kafka, padrão: o tópico do fluxo, "
                "'pedidos.criados' ou 'pagamentos.registrados'). Útil para "
                "reprocessar a DLQ em ambiente de teste."
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
        ativo = mensageria.broker_ativo()
        fluxo = options["fluxo"]
        consumidor = mensageria.criar_consumidor(
            destino=options["destino"],
            max_mensagens=options["max_mensagens"],
            fluxo=fluxo,
        )
        # O log estruturado (logger "core.messaging") é a saída de referência;
        # estas linhas servem para quem está no terminal sem `docker compose logs`.
        self.stdout.write(f"broker ativo: {ativo}")
        self.stdout.write(f"fluxo: {fluxo}")
        self.stdout.write(
            f"worker consumindo {consumidor.descricao_destino()} "
            f"(máx. {options['max_mensagens'] or 'ilimitado'} mensagens)"
        )
        consumidor.rodar()