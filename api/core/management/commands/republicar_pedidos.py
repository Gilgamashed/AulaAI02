"""`manage.py republicar_pedidos` — recupera pedidos que não foram publicados.

Cenário: o `POST /pedidos` grava o pedido e tenta publicar o evento. Se o
broker estiver fora nesse instante, a API responde **503** e o pedido fica
em `pendente_publicacao` — existe no banco, mas o evento não existe na fila.
Este comando é a fila de trabalho manual que fecha esse buraco.

Vale para os dois brokers: a publicação é feita por
`core.messaging.broker.publicar_pedido_criado`, que respeita
`MENSAGERIA_BROKER`. Com o broker errado em ambiente, a republicação vai para
o transporte que o worker **não** está consumindo — por isso o comando imprime
o broker ativo no início e no fim.

Uma correção de projeto que vale notar: a opção "responder 201 e publicar
depois" seria o padrão *transactional outbox*, que exige uma tabela de
outbox, um processo agendador e uma política de limpeza. Isso é mais
robusto, porém é mecanismo de fila — exatamente o que a spec desta aula
proíbe antecipar. Com a fila de pendentes explícita, o estado é observável
(`GET /pedidos/{id}` mostra `pendente_publicacao`) e a recuperação é um
comando idempotente que qualquer pessoa pode rodar.
"""

from core import models
from core.messaging import broker as mensageria
from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone


class Command(BaseCommand):
    help = (
        "Republica na fila os eventos PedidoCriado de pedidos que ficaram em "
        "'pendente_publicacao' (broker fora do ar no momento do POST)."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--pedido",
            type=int,
            default=None,
            help="Republica apenas este pedido (por id). Sem o argumento, varre todos.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=100,
            help="Máximo de pedidos por execução (padrão: 100).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Lista o que seria publicado, sem publicar.",
        )

    def handle(self, *args, **options) -> None:
        broker = mensageria.broker_ativo()
        pendentes = models.Pedido.objects.filter(
            status=models.Pedido.PENDENTE_PUBLICACAO
        ).order_by("created_at")
        if options["pedido"]:
            pendentes = pendentes.filter(pk=options["pedido"])
        pendentes = pendentes[: options["limit"]]

        publicados, falhas = 0, 0
        for pedido in pendentes:
            if options["dry_run"]:
                self.stdout.write(
                    f"[dry-run] republicaria o pedido {pedido.pk} no broker '{broker}'"
                )
                publicados += 1
                continue
            try:
                dados = mensageria.publicar_pedido_criado(pedido, pedido.idempotency_key)
            except mensageria.PublicacaoFalhou as erro:
                falhas += 1
                # `Motivo` curto no console: o detalhe já está no log JSON.
                self.stderr.write(f"pedido {pedido.pk}: {erro}")
                continue
            # Só marca como publicado depois do publisher confirm — o mesmo
            # cuidado do POST: o estado do banco segue o que o broker aceitou.
            #
            # O filtro por `status` é obrigatório pelos mesmos motivos do
            # POST (ver `PedidoViewSet._publicar`): entre o confirm e esta linha
            # o worker pode já ter consumido a mensagem e marcado o pedido
            # como `processado`. Um save sem condição escreveria `pendente`
            # por cima e o pedido ficaria travado nesse estado para sempre —
            # nada mais o moveria, porque o evento já foi consumido.
            models.Pedido.objects.filter(
                pk=pedido.pk, status=models.Pedido.PENDENTE_PUBLICACAO
            ).update(status=models.Pedido.PENDENTE, updated_at=timezone.now())
            publicados += 1
            self.stdout.write(
                f"pedido {pedido.pk}: evento {dados['evento_id']} publicado em "
                f"{dados.get('topico') or dados.get('fila')} via '{broker}' "
                f"({dados['duracao_ms']} ms)"
            )

        # Um pedido `processado` pode ter perdido o evento depois disso (ex.:
        # fila apagada). O comando não reinventa esses casos: quem decide é a
        # inspeção da fila, e o README descreve o caminho de replay manual.
        nao_pendentes = models.Pedido.objects.filter(
            Q(status=models.Pedido.PENDENTE) | Q(status=models.Pedido.FALHA)
        ).count()
        self.stdout.write(
            f"broker='{broker}' publicados={publicados} falhas={falhas} "
            f"(ignorados/ja publicados na fila: {nao_pendentes})"
        )
        if falhas:
            self.stderr.write(
                "houve falhas de publicação; o broker segue indisponível?"
            )
