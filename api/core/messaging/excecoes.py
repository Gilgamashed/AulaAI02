"""Exceções de domínio do processamento de mensagens.

Compartilhadas pelo consumidor AMQP (Aula 9) e pelo consumidor Kafka (Aulas
10-11). Antes deste módulo as duas classes eram definidas uma vez em cada
consumidor: o `except MensagemIncorreta` de um módulo não capturava a do
outro, e a unificação elimina esse caminho silencioso de erro.
"""

from __future__ import annotations


class MensagemIncorreta(Exception):
    """Falha TERMINAL: reentregar não muda nada, então vai direto para a DLQ.

    Difere de uma exceção qualquer do banco, que pode ser transitória. Aqui a
    mensagem está logicamente errada: o pedido não existe, ou a chave de
    idempotência não é a do pedido. Reprocessar dez vezes reproduz o mesmo
    erro e só gasta broker.
    """


class FalhaInjetada(Exception):
    """Falha **de propósito** (header `X-Simular-Falha` no POST).

    Não é um bug: é o mecanismo que prova, ponta a ponta e a cada aula, que a
    escada de reentrega e a DLQ funcionam de verdade — com uma entidade real,
    um log por tentativa e a mensagem parada na DLQ do fluxo no fim
    (`pedidos.criados.dlq` ou `pagamentos.registrados.dlq`).

    Recupérável por definição (é uma exceção comum no laço), então segue o
    mesmo caminho de qualquer falha transitória: reentrega com backoff e, ao
    esgotar, DLQ.
    """
