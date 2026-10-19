"""Mecanismo comum de reentrega: cabeçalhos, contador e decisão da escada.

Compartilhado pelo consumidor AMQP (Aula 9) e pelo consumidor Kafka (Aulas
10-11). O transporte difere (fila com `x-death` × tópico com retenção), mas a
política é a mesma: um contador que viaja na mensagem, uma escada de degraus
(`PEDIDO_BACKOFF_SEGUNDOS`) e uma decisão final — retry do degrau ou DLQ.
Mantê-la num módulo único é o que garante que os dois brokers não divergem
silenciosamente ao serem configurados.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from enum import Enum

from .contracts import ContratoInvalido

# Cabeçalhos da mensagem, idênticos nos dois transportes (o Kafka aceita
# cabeçalhos arbitrários; o AMQP tem os próprios). Valores em str nos dois.
HEADER_TENTATIVA = "x-tentativa"
HEADER_EVENTO_ID = "x-evento-id"
HEADER_MOTIVO = "x-motivo"


class Destino(Enum):
    """Desfecho da decisão de reentrega de uma mensagem com erro."""

    RETRY = "retry"
    DLQ_ESGOTADA = "dlq_esgotada"
    DLQ_SEM_DEGRAU = "dlq_sem_degrau"


def decidir_reentrega(
    tentativa: int, *, max_reentregas: int, degraus: int
) -> Destino:
    """Aplica a escada de reentrega e devolve o destino da mensagem.

    `tentativa >= max_reentregas`: a escada acabou. Já `tentativa + 1 >
    degraus`: a política pede mais reentregas do que existem degraus
    configurados — sem fila/tópico de retry para este degrau, a única rota
    honesta é a DLQ (e o chamador loga isso como `PoliticaInconsistente`).
    """
    if tentativa >= max_reentregas:
        return Destino.DLQ_ESGOTADA
    if tentativa + 1 > degraus:
        return Destino.DLQ_SEM_DEGRAU
    return Destino.RETRY


def degrau_de(tentativa: int) -> int:
    """Índice do degrau da escada para a próxima reentrega (1-based)."""
    return tentativa + 1


def tentativa_de(headers: Mapping[str, object] | None) -> int:
    """Contador de tentativas que viaja nos cabeçalhos da mensagem.

    É o NOSSO contador: sobrevive a qualquer manipulação que o broker faça na
    mensagem e fica explícito no código. (No AMQP convivia com o `x-death` do
    próprio RabbitMQ; no Kafka não existe equivalente de broker, porque a
    retenção não "devolve" a mensagem — ela apaga.)
    """
    bruto = (headers or {}).get(HEADER_TENTATIVA, 0)
    try:
        return int(bruto)  # type: ignore[call-overload,arg-type]
    except (TypeError, ValueError):
        return 0


def desserializar_corpo(corpo: bytes) -> dict:
    """Decodifica JSON UTF-8 ou levanta `ContratoInvalido` (falha terminal).

    Compartilhado pelos dois consumidores: corpo quebrado não conserta com
    reentrega, então o único destino possível é a DLQ.
    """
    try:
        bruto = json.loads(corpo.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as erro:
        raise ContratoInvalido(f"corpo não é JSON UTF-8 válido: {erro}") from erro
    if not isinstance(bruto, dict):
        raise ContratoInvalido("corpo não é um objeto JSON")
    return bruto
