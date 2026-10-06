"""Mensageria assíncrona (Aulas 9, 10 e 11) — fluxo produtor/consumidor.

A spec pede que a política de reentrega, a idempotência e o roteamento para a
Dead Letter Queue sejam visíveis no código do projeto. Por isso este pacote
implementa a topologia **na mão**, com `pika`/`confluent-kafka` e sem Celery:
os exchanges, filas/tópicos, TTLs, offsets e a DLQ são declarados
explicitamente, e o consumidor decide, mensagem a mensagem, o que fazer.

Há **dois transportes** e a escolha é feita por `MENSAGERIA_BROKER`
(`broker.py`). Kafka é o padrão; RabbitMQ continua disponível atrás do profile
`rabbitmq` do compose.

Há também **dois fluxos de evento** (`broker.FLUXOS`), ambos no Kafka:

| Fluxo      | Evento                 | Tópico                  | Worker do compose     |
| ---------- | ---------------------- | ----------------------- | --------------------- |
| `pedidos`  | `PedidoCriado`         | `pedidos.criados`       | `worker-kafka`        |
| `pagamentos`| `PagamentoRegistrado`| `pagamentos.registrados`| `worker-pagamentos`   |

Divisão de responsabilidade:

| Módulo            | Broker  | Responsabilidade                                          |
| ----------------- | ------- | --------------------------------------------------------- |
| `broker`          | ambos   | seleção do transporte; `PublicacaoFalhou` compartilhada    |
| `contracts`       | ambos   | formato dos eventos (`PedidoCriado`, `PagamentoRegistrado`) |
| `dedupe`          | ambos   | janela de idempotência (Redis `SET NX EX`)                |
| `metricas`        | ambos   | contadores do processo, expostos no log estruturado       |
| `erros`           | ambos   | descrição de exceções para o log (tipo + mensagem)        |
| `topologia`       | AMQP    | nomes de exchange/filas, TTLs e declaração idempotente     |
| `produtor`        | AMQP    | publica o evento (usado pela view `POST /pedidos`)        |
| `consumidor`      | AMQP    | o laço de consumo, a idempotência e a política de falhas  |
| `kafka_topologia` | Kafka   | tópicos, partições, retenção, grupos e criação idempotente|
| `kafka_produtor`  | Kafka   | produtor `acks=all` + `enable.idempotence`, singleton     |
| `kafka_consumidor`| Kafka   | consumidor de grupo com commit manual pós-efeito          |
| `kafka_replayer`  | Kafka   | gate de backoff dos tópicos de retry (Kafka não tem TTL)  |

O que é **compartilhado** e por quê importa: contrato, janela de
idempotência, modelo e contadores são os mesmos nos dois brokers. Não existem
dois contratos `PedidoCriado` nem duas janelas de dedupe — o broker muda o
transporte, não o fato de negócio.

O fluxo de pagamento existe **só no Kafka** nesta aula; a razão está em
`broker.publicar_pagamento_registrado` e é uma decisão de escopo, não uma
falta.
"""