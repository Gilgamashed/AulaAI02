"""Descrição de exceções para o log estruturado da mensageria.

Existe por causa de um defeito real observado em produção local: quando o
broker caía, o worker logava

    {"evento": "WorkerSemConexao", "erro": "", "mensagem": "broker indisponível; nova tentativa"}

O campo `erro` vinha de `str(exc)` e várias exceções do `pika` são levantadas
**sem argumentos** (`AMQPConnectionError`, `StreamLostError`), então `str(exc)`
retorna `""`. O sintoma era um log que parecia não ter erro nenhum — exatamente
o oposto do que um log transacional precisa ser, e que ainda por cima
impossibilitava distinguir "broker fora" de "timeout" na análise pós-morte.

A regra é simples: **o tipo da exceção entra sempre no log**. A mensagem
original continua indo junto quando existe, porque o `pika` costuma escrever
detalhes úteis no `__str__` de alguns erros e nada em outros.
"""

from __future__ import annotations


def descrever(exc: BaseException) -> str:
    """Devolve `TipoDaExcecao: mensagem`, ou só o tipo se a mensagem for vazia.

    Serve para todos os campos `erro`/`motivo` do logger `core.messaging`,
    incluindo o `motivo_falha` gravado em `Pedido`: um motivo vazio no banco é
    impossível de diagnosticar depois, quando o processo já morreu.
    """
    nome = type(exc).__name__
    mensagem = str(exc).strip()
    if not mensagem:
        return nome
    return f"{nome}: {mensagem}"
