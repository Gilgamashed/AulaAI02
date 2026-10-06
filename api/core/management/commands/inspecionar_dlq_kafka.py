"""`manage.py inspecionar_dlq_kafka` — o que parou na dead-letter queue.

A DLQ é o único lugar onde um evento que deu problema fica **parado** de
propósito: em vez de sumir numa retenção de 7 dias, ele é retido por 30 e
espera alguém olhar. Este comando é esse "alguém" — ele lê a DLQ sem consumir de
propósito (o `group.id` é um grupo de inspeção, e o offset **não** é
confirmado), mostra o motivo da falha e pode devolver as mensagens para o
tópico principal para reprocessamento.

    python manage.py inspecionar_dlq_kafka               # resumo legível
    python manage.py inspecionar_dlq_kafka --json
    python manage.py inspecionar_dlq_kafka --reprocessar  # devolve tudo
    python manage.py inspecionar_dlq_kafka --fluxo pagamentos

Por que ler sem confirmar offset: a inspeção é de leitura. Um `--reprocessar`
que se confundisse com a leitura (ou um `auto.commit` ligado) apagaria a
evidência do problema no primeiro `docker compose logs | grep PagamentoDlq`. Por
isso o grupo de inspeção nunca é o do worker, e nada é confirmado.

A Aula 11 tem **duas** DLQs (`pedidos.criados.dlq` e
`pagamentos.registrados.dlq`), então o `--fluxo` é obrigatório para escolher —
padrão `pedidos`, que é o que a maioria dos comandos continua querendo. O grupo
de inspeção ganha o sufixo do fluxo: com o mesmo grupo nos dois, a segunda
inspeção leria a partir do offset que a primeira já não confirmou, e pareceria
que a DLQ estava vazia.
"""

from __future__ import annotations

import json
import logging

from core.messaging import broker as mensageria
from core.messaging import kafka_produtor, kafka_topologia
from core.messaging.erros import descrever
from core.messaging.kafka_topologia import HEADER_MOTIVO, HEADER_TENTATIVA
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

logger = logging.getLogger("core.messaging")

# Grupo exclusivo deste comando: separado de `KAFKA_GRUPO_CONSUMIDORES` para
# que a leitura da DLQ nunca afete (nem seja afetada pelo) o consumo normal.
GRUPO_INSPECAO = "synapseshop-dlq-inspecao"


class Command(BaseCommand):
    help = (
        "Lista as mensagens paradas na DLQ do Kafka com o motivo da falha, e "
        "opcionalmente as devolve ao tópico principal para reprocessamento. "
        "Use --fluxo para escolher entre a DLQ de pedidos e a de pagamentos."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--fluxo",
            choices=mensageria.FLUXOS,
            default=mensageria.FLUXO_PEDIDOS,
            help=(
                "Fluxo cuja DLQ será inspecionada: 'pedidos' "
                "(pedidos.criados.dlq) ou 'pagamentos' "
                "(pagamentos.registrados.dlq). Padrão: 'pedidos'."
            ),
        )
        parser.add_argument(
            "--json",
            action="store_true",
            dest="como_json",
            help="Saída em JSON.",
        )
        parser.add_argument(
            "--limite",
            type=int,
            default=20,
            help="Máximo de mensagens listadas (padrão: 20).",
        )
        parser.add_argument(
            "--reprocessar",
            action="store_true",
            help=(
                "Devolve as mensagens listadas ao tópico principal, "
                "confirmando o offset na DLQ. É a ação destrutiva: só use "
                "depois de entender a causa (o motivo está em x-motivo)."
            ),
        )

    def handle(self, *args, **options) -> None:
        if mensageria.broker_ativo() != mensageria.KAFKA:
            raise CommandError(
                "este comando é do Kafka, mas MENSAGERIA_BROKER="
                f"'{settings.MENSAGERIA_BROKER}'."
            )

        from confluent_kafka import Consumer

        topologia = kafka_topologia.TopologiaKafka.do_fluxo(options["fluxo"])
        config = kafka_topologia.config_consumidor(
            f"{GRUPO_INSPECAO}-{topologia.fluxo}", "synapseshop-dlq-inspecao"
        )
        # Grupo fixo (`GRUPO_INSPECAO-<fluxo>`) + `earliest`: a inspeção começa do
        # início da retenção da DLQ toda vez. É o que torna o comando
        # reprodutível — e o que permite ao `--reprocessar` **confirmar** o
        # offset depois de devolver a mensagem, o que só funciona se a próxima
        # execução enxergar o mesmo grupo.
        config["session.timeout.ms"] = 6000

        limite = options["limite"]
        consumidor = Consumer(config)
        mensagens: list[dict] = []
        try:
            consumidor.subscribe([topologia.topico_dlq])
            # `poll` em loop até a DLQ "esgotar": um `poll` que devolve None
            # significa que não há mais nada retido dentro do limite de tempo.
            while len(mensagens) < limite:
                mensagem = consumidor.poll(5.0)
                if mensagem is None:
                    break
                erro = mensagem.error()
                if erro is not None:
                    self.stderr.write(f"erro ao ler a DLQ: {descrever(erro)}")
                    break

                cabecalhos = dict(kafka_produtor.cabecalhos_de(mensagem))
                corpo = (mensagem.value() or b"").decode("utf-8", errors="replace")
                mensagens.append(
                    {
                        "particao": mensagem.partition(),
                        "offset": mensagem.offset(),
                        "chave": (
                            mensagem.key().decode("utf-8", errors="replace")
                            if mensagem.key()
                            else None
                        ),
                        "tentativa": cabecalhos.get(HEADER_TENTATIVA, "?"),
                        "motivo": cabecalhos.get(HEADER_MOTIVO, "(sem x-motivo)"),
                        "evento_id": cabecalhos.get("x-evento-id"),
                        "corpo": corpo,
                        "_referencia": mensagem,
                    }
                )

            if options["reprocessar"]:
                self._reprocessar(consumidor, topologia, mensagens)
        finally:
            consumidor.close()

        visiveis = [_sem_referencia(item) for item in mensagens]
        if options["como_json"]:
            self.stdout.write(
                json.dumps(
                    {
                        "broker": "kafka",
                        "fluxo": topologia.fluxo,
                        "topico_dlq": topologia.topico_dlq,
                        "total_listado": len(visiveis),
                        "reprocessado": bool(options["reprocessar"]),
                        "mensagens": visiveis,
                    },
                    indent=2,
                    ensure_ascii=False,
                    default=str,
                )
            )
            return

        if not visiveis:
            self.stdout.write(f"DLQ '{topologia.topico_dlq}' vazia.")
            return

        self.stdout.write(
            f"{len(visiveis)} mensagem(ns) retida(s) em '{topologia.topico_dlq}':"
        )
        for item in visiveis:
            # A chave é o **pedido_id nos dois fluxos**, e não o id da
            # entidade que originou o evento: `publicar_pagamento_registrado`
            # usa `pagamento.pedido_id` como key pelo mesmo motivo do
            # `PedidoCriado` (ordem por pedido dentro da partição). O que muda
            # entre os fluxos é o que a chave **significa** — aqui a mensagem é
            # de um pagamento do pedido 17, não do pedido 17 em si — então o
            # rótulo diz de que fluxo veio, sem trocar "pedido" por
            # "pagamento": esse número é o pedido nos dois casos.
            self.stdout.write(
                f"  [{item['particao']}/{item['offset']}] "
                f"{topologia.fluxo}:{item['chave']} tentativa {item['tentativa']}"
            )
            self.stdout.write(f"    motivo: {item['motivo']}")
            self.stdout.write(f"    corpo: {item['corpo'][:200]}")

        if not options["reprocessar"]:
            self.stdout.write(
                "\n(sem --reprocessar: nada foi devolvido e nenhum offset foi "
                "confirmado nesta DLQ)"
            )

    def _reprocessar(self, consumidor, topologia, mensagens: list[dict]) -> None:
        """Devolve cada mensagem ao tópico principal e só então confirma a DLQ.

        A ordem é a mesma do consumidor: publica, espera o ACK, confirma o
        offset. Se a publicação falhar, o offset da DLQ **não** é confirmado e
        a mensagem volta a aparecer na próxima inspeção — em vez de evaporar.
        """
        devolvidas = 0
        for item in mensagens:
            mensagem = item["_referencia"]
            # O `x-tentativa` volta a zero, e é o passo que faz o reprocessamento
            # servir para alguma coisa. Sem isso a mensagem volta com
            # `tentativa = max_reentregas`, o worker a reprocessa uma única vez
            # e a manda direto de volta para a DLQ — e o comando reporta
            # "devolvida ao tópico principal" como se tivesse funcionado. É um
            # `--reprocessar` que não reprocessa, e o sintoma (mensagem que
            # reaparece na DLQ sem ninguém a ter colocado lá) não aponta para o
            # header.
            #
            # `x-motivo` sai porque descreve a falha **daquela** tentativa; a
            # tentativa nova ainda não tem motivo.
            cabecalhos = [
                (nome, valor)
                for nome, valor in kafka_produtor.cabecalhos_de(mensagem)
                if nome not in (HEADER_MOTIVO, HEADER_TENTATIVA)
            ]
            cabecalhos.append((HEADER_TENTATIVA, "0"))
            try:
                kafka_produtor.republicar(
                    topologia.topico,
                    mensagem.value() or b"",
                    chave=item["chave"],
                    cabecalhos=cabecalhos,
                    client_id="synapseshop-dlq-reprocessa",
                )
            except Exception as erro:  # noqa: BLE001 - PublicacaoFalhou e Kafka
                self.stderr.write(
                    f"  offset {mensagem.offset()}: falha ao republicar "
                    f"({descrever(erro)}); mantido na DLQ"
                )
                continue

            consumidor.commit(message=mensagem, asynchronous=False)
            devolvidas += 1
            logger.warning(
                "mensagem devolvida da DLQ para reprocessamento",
                extra={
                    "evento": "DlqReprocessada",
                    "resultado": "ok",
                    "broker": "kafka",
                    "fluxo": topologia.fluxo,
                    "fila": topologia.topico_dlq,
                    "topico": topologia.topico_dlq,
                    "destino": topologia.topico,
                    "particao": mensagem.partition(),
                    "offset": mensagem.offset(),
                },
            )
        self.stdout.write(f"{devolvidas} mensagem(ns) devolvida(s) ao tópico principal.")


def _sem_referencia(item: dict) -> dict:
    """Copia o item sem o objeto `Message`, que não é serializável."""
    return {chave: valor for chave, valor in item.items() if chave != "_referencia"}