"""Topologia AMQP da Aula 9: exchanges, filas e a política de reentrega.

Diagrama (setas = `basic_publish` do produtor e do worker):

    POST /pedidos
        │
        │ publica em `pedidos` (topic) com routing key `pedido.criado`
        v
   ┌─────────────────────┐
   │ exchange  pedidos   │
   └──────────┬──────────┘
              │ binding pedido.criado
              v
   ┌─────────────────────┐        falha (1ª..3ª)      ┌──────────────────┐
   │ fila pedidos.criados│ ────────────────────────> │ exchange         │
   └──────────┬──────────┘                           │  pedidos.retry   │
              │                                      └────┬──────┬──────┘
              │ tentativa esgotada / contrato inválido   │      │
              │                                           │      │
              │                                           v      v
              │                          ┌───────────┐ ┌───────────┐
              │                          │ retry.1   │ │ retry.2   │ ... retry.N
              │                          │ TTL 5 s   │ │ TTL 15 s  │
              │                          └─────┬─────┘ └─────┬─────┘
              │                                │ x-dead-letter-exchange = pedidos
              │                                └──────┬──────┘
              │                                       │ routing key pedido.criado
              └───────────────────────────────────────┘  (volta à fila principal)

              v
   ┌─────────────────────┐
   │ exchange  pedidos.dlx│  <── qualquer falha terminal
   └──────────┬──────────┘
              │ binding pedido.criado
              v
   ┌─────────────────────┐
   │ pedidos.criados.dlq │  (terminal, sem TTL: fica para inspeção/replay)
   └─────────────────────┘

Três decisões que valem registro:

1. **O atraso da reentrega fica no broker, não no worker.** Cada degrau da
   escada é uma fila com `x-message-ttl`; quando o TTL expira, o próprio
   RabbitMQ devolve a mensagem à fila principal. Um `time.sleep()` no
   consumidor manteria o processo ocupado e, pior, perderia a contagem de
   tentativas se o container reiniciasse no meio da espera.

2. **A mensagem que vai para a retry é uma NOVA publicação com
   `publisher confirm`, e só então a original recebe `ack`.** O caminho
   inverso (nack + requeue na fila principal) seria mais simples, mas
   reentrega na hora, sem backoff, e com o risco de "loop apertado" quando a
   falha é permanente.

3. **A fila principal também tem DLX.** A reentrega explícita cobre as
   falhas que *sabemos* que são transitórias; a DLX declarado é a rede de
   segurança para o que não passa por esse caminho — por exemplo, uma
   mensagem rejeitada porque a conexão do worker caiu no meio do
   processamento (`nack(requeue=False)`).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import pika
from django.conf import settings

logger = logging.getLogger("core.messaging")

EXCHANGE_RETRY = "pedidos.retry"
EXCHANGE_DLQ = "pedidos.dlx"

# Routing keys de retry: `retry.1`, `retry.2`, ... (exchange `direct`).
PREFIXO_ROUTING_RETRY = "retry."

# Headers AMQP usados pela política de reentrega.
# `x-tentativa` é o NOSSO contador (sobrevive a qualquer coisa que o broker
# faça com a mensagem); `x-death` é o contador do próprio RabbitMQ, que
# registra cada vez que a mensagem passou por uma fila com TTL/dead-letter.
HEADER_TENTATIVA = "x-tentativa"
HEADER_EVENTO_ID = "x-evento-id"
HEADER_MOTIVO = "x-motivo"


def nomes_retry() -> list[tuple[int, str]]:
    """Lista `(índice, nome_da_fila)` de retry, na ordem da escada.

    Deriva de `PEDIDO_BACKOFF_SEGUNDOS`, então mudar a variável de ambiente
    muda a quantidade de filas de retry declaradas — não há constante
    "mágica" de 3 degraus escondida no código.
    """
    return [
        (indice + 1, f"{settings.PEDIDO_FILA}.retry.{indice + 1}")
        for indice in range(len(settings.PEDIDO_BACKOFF_SEGUNDOS))
    ]


def segundos_do_degrau(indice: int) -> int:
    """Atraso (s) do degrau `indice` (1-based) da escada de reentrega."""
    return settings.PEDIDO_BACKOFF_SEGUNDOS[indice - 1]


@dataclass(frozen=True)
class Topologia:
    """Nomes resolvidos da topologia (lidos das settings em um só lugar)."""

    exchange: str
    routing_key: str
    fila: str
    exchange_retry: str
    exchange_dlx: str
    fila_dlq: str

    @classmethod
    def do_ambiente(cls) -> Topologia:
        return cls(
            exchange=settings.PEDIDO_EXCHANGE,
            routing_key=settings.PEDIDO_ROUTING_KEY,
            fila=settings.PEDIDO_FILA,
            exchange_retry=EXCHANGE_RETRY,
            exchange_dlx=EXCHANGE_DLQ,
            fila_dlq=settings.PEDIDO_FILA_DLQ,
        )

    def fila_retry(self, indice: int) -> str:
        return f"{self.fila}.retry.{indice}"

    def routing_key_retry(self, indice: int) -> str:
        return f"{PREFIXO_ROUTING_RETRY}{indice}"

    def resumo(self) -> dict[str, Any]:
        """Dicionário serializável da topologia (entra no log de startup)."""
        return {
            "exchange": self.exchange,
            "routing_key": self.routing_key,
            "fila": self.fila,
            "exchange_retry": self.exchange_retry,
            "filas_retry": [
                {"fila": self.fila_retry(i), "ttl_s": segundos_do_degrau(i)}
                for i in range(1, len(settings.PEDIDO_BACKOFF_SEGUNDOS) + 1)
            ],
            "exchange_dlx": self.exchange_dlx,
            "fila_dlq": self.fila_dlq,
            "max_reentregas": settings.PEDIDO_MAX_REENTREGAS,
        }


def parametros_conexao() -> pika.URLParameters:
    """`URLParameters` com timeouts explícitos.

    Sem `socket_timeout`/`blocked_connection_timeout`, uma queda silenciosa
    do broker deixa a thread de requisição esperando indefinidamente — no
    produtor isso travaria uma requisição HTTP, e no worker travaria o `ack`.
    """
    parametros = pika.URLParameters(settings.RABBITMQ_URL)
    parametros.socket_timeout = 5
    parametros.stack_timeout = 10
    parametros.blocked_connection_timeout = 5
    parametros.heartbeat = 60
    parametros.connection_attempts = 3
    parametros.retry_delay = 2
    return parametros


def abrir_conexao() -> pika.BlockingConnection:
    """Abre uma conexão AMQP nova.

    `pika.BlockingConnection` **não é segura para uso concorrente**: a mesma
    conexão não pode ser compartilhada entre threads. Como o produtor roda
    dentro de um processo do gunicorn que atende várias threads, a decisão
    simples e honesta é abrir uma conexão por publicação. Num broker local o
    custo é de poucos milissegundos, e ele aparece medido no log
    (`duracao_ms` de `PedidoPublicado`) — se virar gargalo, o próximo passo
    é um pool de conexões por thread, não compartilhar uma.
    """
    return pika.BlockingConnection(parametros_conexao())


def declarar_topologia(canal: pika.adapters.blocking_connection.BlockingChannel) -> Topologia:
    """Declara exchanges e filas. Idempotente: pode rodar em todo startup.

    Declarar é `INSERT ... IF NOT EXISTS` no mundo AMQP: chamar com os mesmos
    nomes e argumentos é um no-op. Por isso tanto o produtor quanto o worker
    chamam esta função no início — não existe "ordem de subida" entre eles,
    e o primeiro que subir cria a topologia.
    """
    topologia = Topologia.do_ambiente()

    # `topic` no exchange de domínio: separa o roteamento do nome da fila, o
    # que permite futuras filas por consumidor (`pagamento.*`, `notificacao.*`)
    # sem renomear nada.
    canal.exchange_declare(
        exchange=topologia.exchange, exchange_type="topic", durable=True
    )
    canal.exchange_declare(
        exchange=topologia.exchange_retry, exchange_type="direct", durable=True
    )
    canal.exchange_declare(
        exchange=topologia.exchange_dlx, exchange_type="direct", durable=True
    )

    # Rede de segurança: o que for rejeitado sem requeue (worker morto no
    # meio do processamento) cai direto na DLQ em vez de ficar preso.
    canal.queue_declare(
        queue=topologia.fila,
        durable=True,
        arguments={
            "x-dead-letter-exchange": topologia.exchange_dlx,
            "x-dead-letter-routing-key": topologia.routing_key,
        },
    )
    canal.queue_bind(
        queue=topologia.fila,
        exchange=topologia.exchange,
        routing_key=topologia.routing_key,
    )

    for indice in range(1, len(settings.PEDIDO_BACKOFF_SEGUNDOS) + 1):
        fila_retry = topologia.fila_retry(indice)
        canal.queue_declare(
            queue=fila_retry,
            durable=True,
            arguments={
                "x-message-ttl": segundos_do_degrau(indice) * 1000,
                # Ao expirar o TTL, o broker devolve a mensagem para a fila
                # principal, na rota normal — é isso que faz o backoff.
                "x-dead-letter-exchange": topologia.exchange,
                "x-dead-letter-routing-key": topologia.routing_key,
            },
        )
        canal.queue_bind(
            queue=fila_retry,
            exchange=topologia.exchange_retry,
            routing_key=topologia.routing_key_retry(indice),
        )

    # DLQ terminal: sem TTL e sem dead-letter, para que a mensagem fique lá
    # para ser inspecionada (e reenviada manualmente) em vez de sumir.
    canal.queue_declare(queue=topologia.fila_dlq, durable=True)
    canal.queue_bind(
        queue=topologia.fila_dlq,
        exchange=topologia.exchange_dlx,
        routing_key=topologia.routing_key,
    )

    logger.info(
        "topologia declarada",
        extra={
            "evento": "TopologiaDeclarada",
            "resultado": "ok",
            "detalhe": topologia.resumo(),
        },
    )
    return topologia
