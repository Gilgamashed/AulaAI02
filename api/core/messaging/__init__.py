"""Mensageria assíncrona da Aula 9 (RabbitMQ) — fluxo produtor/consumidor.

A spec pede que a política de reentrega, a idempotência e o roteamento para a
Dead Letter Queue sejam visíveis no código do projeto. Por isso este pacote
implementa a topologia **na mão**, com `pika` e sem Celery: o exchange, as
filas de retry, os TTLs e a DLQ são declarados explicitamente
(`topologia.py`), e o consumidor decide, mensagem a mensagem, o que fazer
(`consumidor.py`).

Divisão de responsabilidade:

| Módulo        | Responsabilidade                                        |
| ------------- | ------------------------------------------------------- |
| `contracts`   | o formato do evento `PedidoCriado` (o contrato da API)   |
| `topologia`   | nomes de exchange/filas, TTLs e declaração idempotente   |
| `produtor`    | publica o evento (usado pela view `POST /pedidos`)       |
| `dedupe`      | janela de idempotência (Redis `SET NX EX`)                |
| `consumidor`  | o laço de consumo, a idempotência e a política de falhas  |
| `metricas`    | contadores do processo, expostos no log estruturado      |
| `erros`       | descrição de exceções para o log (tipo + mensagem)       |
"""
