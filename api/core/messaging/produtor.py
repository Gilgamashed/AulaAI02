"""Produtor: publica o evento `PedidoCriado` na fila (Aula 9).

Usado pela view `POST /api/v1/pedidos`. Três garantias importam aqui:

1. **Publisher confirms.** `basic_publish` só enfileira no processo do
   broker; quem garante que a mensagem foi *persistida* é o `confirm`, que o
   broker devolve depois de gravar. Sem ele, um `basic_publish` "bem-sucedido"
   numa queda do broker seria um evento perdido — e evento perdido é pedido
   que nunca é processado.

2. **`mandatory=True`.** Se a mensagem não couber em nenhuma fila (binding
   removido, topologia errada), o broker a devolve em vez de descartá-la em
   silêncio. Sem isso, "publicado com sucesso" seria uma mentira.

3. **Propriedades AMQP explícitas.** `delivery_mode=2` (persistente), para a
   mensagem sobreviver a um restart do broker; `message_id`, `type` e
   `timestamp` para ferramentas de diagnóstico (UI do RabbitMQ, `rabbitmqctl`)
   lerem algo útil sem precisar abrir o corpo.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import pika
from django.conf import settings

from .. import models
from . import contracts
from .erros import descrever
from .topologia import (
    HEADER_EVENTO_ID,
    HEADER_MOTIVO,
    HEADER_TENTATIVA,
    Topologia,
    abrir_conexao,
    declarar_topologia,
)

logger = logging.getLogger("core.messaging")


class PublicacaoFalhou(Exception):
    """O evento não pôde ser publicado (broker fora, topologia, timeout).

    Levanta para a view responder **503** e manter o pedido em
    `pendente_publicacao`. A alternativa — responder 201 e tentar publicar
    depois — é o outbox pattern, que exige mais uma tabela e um processo
    agendador: fora do escopo desta aula.
    """


def publicar_pedido_criado(pedido: models.Pedido, idempotency_key: str) -> dict[str, Any]:
    """Publica o evento e devolve os dados de publicação (id do evento, tempo).

    Levanta `PublicacaoFalhou` em qualquer erro do broker. O corpo do evento é
    montado **antes** de abrir a conexão: se a serialização falhar, é um bug
    do contrato e não uma indisponibilidade do broker, e a mensagem de erro
    precisa dizer isso.
    """
    corpo = contracts.construir_pedido_criado(pedido, idempotency_key)
    dados = contracts.serializar(corpo)
    topologia = Topologia.do_ambiente()

    inicio = time.perf_counter()
    try:
        conexao = abrir_conexao()
    except (pika.exceptions.AMQPError, OSError) as erro:
        # `OSError` junto do `AMQPError` não é redundância: com o container do
        # broker parado (ou removido da rede do Compose), a falha aparece
        # ANTES do AMQP — é o `getaddrinfo`/socket que estoura com
        # `socket.gaierror`/`ConnectionError`, e nenhum dos dois é `AMQPError`.
        # Sem esta linha o POST respondia 500 em vez de 503, e o cliente
        # recebia "erro do servidor" em vez de "o broker está fora".
        _log_falha(pedido, corpo, erro, 0.0)
        raise PublicacaoFalhou(f"conexão com o broker falhou: {erro}") from erro

    try:
        with conexao:
            canal = conexao.channel()
            # Idempotente: quem subir primeiro (API ou worker) cria a topologia.
            declarar_topologia(canal)
            # Transforma `basic_publish` em modo confirmado: o broker responde
            # depois de gravar em disco (com a fila durable + delivery_mode 2).
            canal.confirm_delivery()

            published = canal.basic_publish(
                exchange=topologia.exchange,
                routing_key=topologia.routing_key,
                body=dados,
                mandatory=True,
                properties=pika.BasicProperties(
                    content_type="application/json",
                    content_encoding="utf-8",
                    delivery_mode=2,  # persistente
                    message_id=corpo["evento_id"],
                    type=contracts.EVENTO_PEDIDO_CRIADO,
                    timestamp=int(time.time()),
                    headers={
                        HEADER_TENTATIVA: 0,
                        HEADER_EVENTO_ID: corpo["evento_id"],
                    },
                ),
            )
            if published is False:
                # `basic_publish` só devolve False quando a conexão caiu no meio
                # da confirmação; nesse caso o estado da mensagem é desconhecido
                # e tratar como sucesso seria mentir para o cliente.
                # Nome próprio (`nao_confirmada`): `erro` é desvinculado pelo
                # `except` do bloco seguinte e reutilizá-lo aqui sombrearia.
                nao_confirmada = pika.exceptions.AMQPError("broker não confirmou a publicação")
                _log_falha(pedido, corpo, nao_confirmada, time.perf_counter() - inicio)
                raise PublicacaoFalhou("broker não confirmou a publicação") from nao_confirmada
    except PublicacaoFalhou:
        raise
    except (pika.exceptions.AMQPError, OSError) as erro:
        _log_falha(pedido, corpo, erro, time.perf_counter() - inicio)
        raise PublicacaoFalhou(f"publicação falhou: {erro}") from erro

    duracao_ms = (time.perf_counter() - inicio) * 1000
    logger.info(
        "evento publicado",
        extra={
            "evento": "PedidoPublicado",
            "resultado": "ok",
            "evento_id": corpo["evento_id"],
            "chave_idempotencia": idempotency_key,
            "pedido_id": pedido.pk,
            "fila": topologia.fila,
            "duracao_ms": round(duracao_ms, 3),
            "tentativa": 0,
        },
    )
    return {
        "evento_id": corpo["evento_id"],
        "fila": topologia.fila,
        "routing_key": topologia.routing_key,
        "duracao_ms": round(duracao_ms, 3),
        "ocorrido_em": corpo["ocorrido_em"],
        # O relógio do produtor em epoch ms: é o que permite ao cliente (e ao
        # `scripts/measure_messaging.py`) medir a latência da fila sem
        # depender de quando ele perguntou.
        "publicado_em": corpo["publicado_em"],
    }


def republicar(
    canal: pika.adapters.blocking_connection.BlockingChannel,
    corpo: bytes,
    propriedades: pika.BasicProperties,
    exchange: str,
    routing_key: str,
) -> None:
    """Republica uma mensagem em outro destino, no canal já confirmado.

    É o caminho das DLQs internas (retry e DLQ). Receber o `canal` em vez de
    abrir uma conexão é proposital: quem chama já tem um canal em modo
    `confirm_delivery()`, e só pode dar `ack` na mensagem original **depois**
    que esta publicação for confirmada. Se a republicação falhar, o `ack` não
    acontece e o broker devolve a mensagem à fila principal — nada se perde.
    """
    confirmacao = canal.basic_publish(
        exchange=exchange,
        routing_key=routing_key,
        body=corpo,
        mandatory=True,
        properties=propriedades,
    )
    if confirmacao is False:
        raise pika.exceptions.AMQPError(
            f"broker não confirmou a republicação em {exchange}:{routing_key}"
        )


def com_tentativa(
    propriedades: pika.BasicProperties,
    tentativa: int,
    *,
    motivo: str | None = None,
) -> pika.BasicProperties:
    """Copia as propriedades AMQP com o contador de tentativa incrementado.

    O contador viaja na própria mensagem, então sobrevive à passagem pela
    fila de retry, ao restart do worker e à leitura por qualquer outro
    consumidor. É o que permite decidir "reentregar ou mandar para a DLQ"
    sem depender de memória do processo.

    `motivo` vai para o header `x-motivo`: quando alguém inspecionar uma
    mensagem presa na DLQ, a causa da falha está no cabeçalho, sem precisar
    correlacionar com o log de outro processo.
    """
    headers = dict(propriedades.headers or {})
    headers[HEADER_TENTATIVA] = tentativa
    if motivo:
        headers[HEADER_MOTIVO] = motivo[:200]
    return pika.BasicProperties(
        content_type=propriedades.content_type,
        content_encoding=propriedades.content_encoding,
        delivery_mode=propriedades.delivery_mode,
        message_id=propriedades.message_id,
        type=propriedades.type,
        timestamp=propriedades.timestamp,
        headers=headers,
    )



def _log_falha(
    pedido: models.Pedido,
    corpo: dict[str, Any],
    erro: Exception,
    duracao_ms: float,
) -> None:
    logger.error(
        "falha ao publicar o evento",
        extra={
            "evento": "PedidoPublicacaoFalhou",
            "resultado": "erro",
            "evento_id": corpo.get("evento_id"),
            "chave_idempotencia": corpo.get("idempotency_key"),
            "pedido_id": pedido.pk,
            "duracao_ms": round(duracao_ms, 3),
            "erro": descrever(erro),
            "motivo": (
                "pedido mantido em "
                f"{settings.PEDIDO_ESTADO_INICIAL}; rode `republicar_pedidos` "
                "ou reenvie o POST com a mesma Idempotency-Key"
            ),
        },
    )
