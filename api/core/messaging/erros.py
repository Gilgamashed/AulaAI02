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

# Implementação única em `core.erros` (módulo pai); o re-export mantém o
# caminho histórico `core.messaging.erros.descrever` estável para os
# consumidores, productores e commands que já importam daqui.
from ..erros import descrever as descrever
