# Contrato `PedidoCriado` — versão 1

Este documento descreve o **evento de domínio** publicado pela API assim que um `Pedido` é criado com sucesso. Ele é a fronteira entre o **projeto síncrono (API)** e o **projeto assíncrono (worker)**, na Aula 9.

*Versão*: `1`
*Evento*: `PedidoCriado`
*Origem*: `synapseshop-api`

## 1. Por que existe este contrato

* **Desacoplamento**: o POST cria o pedido e responde **201** assim que o broker confirma a publicação (publicação confirmada). O processamento pesado ou qualquer efeito colateral acontece fora da requisição.
* **Idempotência ponta a ponta**: a `idempotency_key` viaja no evento e, com a janela no **Redis (db 0)** e o `UPDATE` condicional no **PostgreSQL**, o worker nunca duplica o efeito, mesmo com reentregas.
* **Auditabilidade**: o evento contém apenas os campos mínimos de negócio e um carimbo de publicação (`publicado_em`) para medição de latência de fila.
* **Tolerância a falhas**: o consumidor valida o contrato (falha **terminal** → DLQ), aplica política de reentrega com backoff exponencial (5s/15s/45s) e marca o pedido como `falha` ao esgotar as tentativas.

## 2. O corpo do evento

```json
{
  "evento": "PedidoCriado",
  "versao": 1,
  "evento_id": "0f9c1e6c-2c1f-4a0a-9a3f-6b1d2c4e5f70",
  "idempotency_key": "9f2c...64 hex",
  "origem": "synapseshop-api",
  "ocorrido_em": "2026-09-30T12:00:00.000Z",
  "publicado_em": 1759243200123,
  "pedido": {
    "id": 42,
    "usuario_id": 2,
    "status": "pendente",
    "total": "1299.90",
    "itens": [
      {"sku": "MED-0499", "quantidade": 2, "preco_unitario": "1998.00"}
    ]
  }
}
```

## 3. Campos e regras

| Campo | Tipo | Obrigatório | Notas |
|---|---|---|---|
| `evento` | `string` | Sim | Deve ser `"PedidoCriado"`. |
| `versao` | `integer` | Sim | Contrato v1: `1`. Consumidores que receberem versão diferente rejeitam (DLQ). |
| `evento_id` | `string` (UUID v4) | Sim | Identificador único do evento (correlaciona logs do produtor e do consumidor). |
| `idempotency_key` | `string` (hex/64 máx.) | Sim | Chave que origina a idempotência. `POST /pedidos` herda do header `Idempotency-Key` ou deriva SHA-256 do pedido. Viaja no evento para fechar a barreira no worker. |
| `origem` | `string` | Sim | `"synapseshop-api"`. |
| `ocorrido_em` | `string` (ISO-8601 UTC) | Sim | Instante em que o fato ocorreu (Django UTC). Formato `YYYY-MM-DDTHH:mm:ss.sssZ`. |
| `publicado_em` | `integer` (epoch ms) | Sim | **Relógio do produtor no momento da publicação** (usado pelo worker para medir `atraso_fila_ms`). Importante para latência end-to-end reproduzível. |
| `pedido.id` | `integer` | Sim | Chave primária do pedido no PostgreSQL (o consumidor atualiza por este ID). |
| `pedido.usuario_id` | `integer` | Sim | Dono do pedido (permite auditoria e restrições de leitura). |
| `pedido.status` | `string` | Sim | Estado no momento da publicação: `pendente_publicacao` → depois do publisher confirm vira `pendente` (API) ou `processado` (worker). O contrato registra o snapshot. |
| `pedido.total` | `string` (decimal) | Sim | **Sempre string**. `Decimal` não é JSON: usar `float` perde precisão. Ex.: `"1299.90"`. |
| `pedido.itens` | `array` (>=1) | Sim | Linhas do pedido com snapshot do preço unitário no momento da compra. |
| `pedido.itens[].sku` | `string` | Sim | Identificador do produto no catálogo. |
| `pedido.itens[].quantidade` | `integer` (>=1) | Sim | Quantidade solicitada. |
| `pedido.itens[].preco_unitario` | `string` (decimal) | Sim | Snapshot do preço de venda (não vem do cliente; vem do catálogo). |

### Decisão de modelagem: o que **não** vai no evento

* Não são incluídos `created_at`, `updated_at`, `processado_em`, `tentativas`, `motivo_falha`, `simular_falha` nem dados do usuário (nome/email). O evento é o **fato "pedido criado"** (com os dados necessários para aplicá-lo), não um dump completo do registro. O banco permanece a fonte única de verdade para esses campos.

## 4. Serialização

* Corpo em JSON UTF-8, sem BOM.
* Números monetários como strings (ver regra acima).
* `publicado_em` é `int` (epoch milissegundos) para cálculo direto de latência sem comparar strings ISO.
* `evento_id` é UUID v4 (gera-se no produtor: `uuid.uuid4()`).

## 5. Validação e tratamento de erros

O consumidor (`core.messaging.kafka_consumidor`) valida **estritamente** o payload com `core.messaging.contracts.validar_pedido_criado`:

1. **Tipo**: objeto JSON.
2. **Top-level**: `evento`, `versao`, `evento_id`, `idempotency_key`, `origem`, `ocorrido_em`, `publicado_em`, `pedido`.
3. **Pedido**: deve ser objeto com `id`, `usuario_id`, `status`, `total`, `itens` (lista não vazia).
4. **Itens**: cada item com `sku` não vazio, `quantidade` inteiro >= 1, `preco_unitario` decimal válido.
5. **Versão**: se `versao != 1` → `ContratoInvalido` → **DLQ imediata** (falha terminal; reentregar não conserta).
6. **Evento desconhecido**: diferente de `PedidoCriado` → `ContratoInvalido` → **DLQ**.

## 6. Publicação e entrega

O transporte padrão é o **Apache Kafka** (Aula 10); o RabbitMQ da Aula 9
continua como implementação alternativa, escolhida por `MENSAGERIA_BROKER`. O
payload é **idêntico nos dois** — muda a topologia, não o contrato.

### Kafka (padrão)

* **Tópico principal**: `pedidos.criados`, com **3 partições**. A chave de
  produção é `str(pedido.id)`, então todos os eventos do mesmo pedido caem na
  mesma partição e a ordem por pedido é preservada.
* **Retenção**: `retention.ms` por tópico — 7 dias no principal
  (`KAFKA_RETENCAO_MS`), 30 dias na DLQ (`KAFKA_RETENCAO_DLQ_MS`).
* **Confirmações**: `acks=all` com `enable.idempotence=true`, e `flush()` antes
  do 201. O POST só responde **201** depois do broker confirmar. Se a
  confirmação falhar, o pedido fica em `status = pendente_publicacao` e a API
  responde **503** com instrução para `manage.py republicar_pedidos`.
* **Consumo**: `enable.auto.commit=false` e `enable.auto.offset.store=false`. O
  offset é confirmado (`commit(message=…)`, síncrono) só **depois** do efeito
  aplicado. Um consumidor por partição no máximo.
* **Producer singleton** por processo: abrir um `Producer` por POST custa ~30 ms
  de conexão, e o cliente único reaproveitado é o que faz o POST cair de ~1,4 s
  para ~160 ms.

### RabbitMQ (alternativa, profile `rabbitmq`)

* **Exchange**: `pedidos` (tipo `topic`), routing key `pedido.criado`.
* **Fila principal**: `pedidos.criados` (durável), DLX `pedidos.dlx` com routing
  key `pedido.criado` (fallback caso o consumidor rejeite sem routing key
  explícita).
* **Confirmações**: `channel.confirm_delivery()`; o POST só responde 201 depois
  da confirmação.
* **Durabilidade**: exchanges e filas duráveis, mensagens persistentes.

## 7. Idempotência (ponta a ponta)

A chave viaja no evento e é usada em **duas barreiras**, independentes:

* **Barreira 1 — Redis (db 0), janela de idempotência**: `dedupe.reservar(evento)` faz `SET key NX EX ttl` (TTL configurável). Se a chave já existe → mensagem é **duplicata**: confirmação de offset (ou `ack`) sem aplicar efeito, log `PedidoDuplicado`.
* **Barreira 2 — PostgreSQL**: `UPDATE` condicional com filtro `status__in(ESTADOS_PROCESSAVEIS)` **e** `idempotency_key = evento.idempotency_key`. Resultado 0 linhas:
  * se o pedido já está `processado` → duplicata real, log `PedidoDuplicado` (efeito já aplicado).
  * se a chave não confere com o pedido → `MensagemIncorreta` → **DLQ** (terminal).
  * se o pedido não existe → `MensagemIncorreta` → **DLQ**.

A janela do Redis evita reprocessar a mesma mensagem enquanto ela ainda está "em trânsito", e o UPDATE condicional é a autoridade final (garantia mesmo com Redis indisponível ou janela expirada).

## 8. Reentregas e DLQ

* **Tentativa inicial**: `tentativa = 0` (header **`x-tentativa`**,
  `core.messaging.kafka_topologia.HEADER_TENTATIVA`). No RabbitMQ é um header
  AMQP; no Kafka, o mesmo par chave/valor nos headers da mensagem.
* **Backoff**: em caso de exceção recuperável, a mensagem é publicada em
  `pedidos.criados.retry.{d}` para `d = 1..3`.
  * **Kafka**: o degrau é a **própria retenção do tópico**
    (`610000 / 630000 / 690000 ms`, ou seja, 5/15/45 s + folga). O replayer
    (`synapseshop-replay`) só lê o tópico e republica no principal quando o
    offset da mensagem é anterior a `agora - backoff`; como a retenção expira
    logo depois, a janela é curta. Não há timer no worker: reiniciá-lo não
    reinicia a espera.
  * **RabbitMQ**: `x-message-ttl` em segundos `5,15,45`, e a expiração
    redireciona para a fila principal via `x-dead-letter-exchange`.
* **Escada**: `max_reentregas = 3` → até 3 reentregas após a tentativa inicial
  (total de 4 passagens). Com `X-Simular-Falha: 1`, o E2E medido terminou em
  `status = falha` com `tentativas = 4` e a mensagem na DLQ.
* **DLQ**: se `tentativa >= max_reentregas` **OU** política inconsistente (faltam
  degraus) **OU** `ContratoInvalido` **OU** `MensagemIncorreta` → a mensagem vai
  para `pedidos.criados.dlq` e o consumidor confirma o offset (ou faz `ack`).
  Quando vai por tentativas esgotadas, o pedido é marcado como `status = falha`
  e `motivo_falha` registra a última exceção (truncada em 200 caracteres).

### `tentativas` no banco e passagens pela escada

`Pedido.tentativas` conta **as passagens totais**, e é por isso que o valor
final é **4**, não 3: a tentativa inicial também é contada. Um defeito
corrigido nesta aula contava a falha terminal duas vezes (o `UPDATE` de
`falha` incrementava e a publicação na DLQ incrementava de novo), o que
produzia `tentativas = 5` para 4 passagens. A lição: um contador de
tentativas que é escrito em dois lugares para o mesmo evento vai acabar
contando errado, e o banco precisa ser a única fonte.

### Auditoria da passagem (Kafka)

No Kafka **não** existe equivalente ao `x-death` do RabbitMQ: a retenção não
"devolve" a mensagem, ela apaga. A auditoria passa a ser o **timestamp do
broker** gravado no header `x-timestamp-ms` a cada republicação, mais o evento
de log `RetryLiberada` com `espera_ms` — que mede o tempo que o degrau segurou a
mensagem de fato:

```json
{"evento": "RetryLiberada", "resultado": "ok", "degrau": 2,
 "topico": "pedidos.criados.retry.2", "espera_ms": 15009,
 "mensagem": "degrau de reentrega expirado; republicando"}
```

`espera_ms` de ~15 s no degrau 2 é a prova de que o backoff de 5/15/45 s
acontece **no tópico**, e não num `sleep` do processo. A leitura da DLQ
(`manage.py inspecionar_dlq_kafka`) devolve `particao`, `offset`, `tentativa`,
`motivo`, `evento_id` e o payload, e **não confirma offset** — inspecionar não
consome.

## 9. Simulação de falha (validação)

Para provar a escada ponta a ponta sem introduzir bugs artificiais no código de negócio, o POST aceita o header `X-Simular-Falha: 1` **somente** quando `PEDIDO_PERMITIR_SIMULACAO_FALHA` for verdadeiro (padrão `true` em desenvolvimento). Esse flag é gravado em `Pedido.simular_falha` e **lido do banco pelo consumidor**: ao processar o evento, se `simular_falha` for `True`, o consumidor levanta `FalhaInjetada` (exceção recuperável), forçando a reentrega até esgotar a escada e terminar na DLQ.

## 10. Observabilidade

* **Logs JSON** (`core.messaging`): **45 tipos de evento** (lista conferida
  contra o código por grep de `"evento":`, não de memória). Ciclo da mensagem:
  `MensagemRecebida`, `MensagemEncerrada`, `PedidoProcessado`,
  `PedidoDuplicado`, `PedidoFalha`, `PedidoDlq`, `ErroConsumo`. Publicação:
  `PedidoPublicado`, `PedidoPublicacaoFalhou`, `ProdutorCriado`,
  `ProdutorFechando`. Topologia: `TopicosDeclarados`, `TopicosDescritos`,
  `TopicosPurgados`, `OffsetsResetados`. Offset: `OffsetCommitFalhou`,
  `OffsetCommitIgnorado`, `ReentregaFalhou`, `GruposIndisponiveis`. Replay:
  `ReplayerIniciado`, `ReplayerConectado`, `RetryLiberada`, `RetryRetomado`,
  `RetryAguardando`, `RetrySemTimestamp` e os `Replayer*` de falha. Worker:
  `WorkerIniciado`, `WorkerEncerrando`, `WorkerEncerrado`, `WorkerParando`,
  `WorkerInterrompido`, `WorkerLimiteAtingido`, `WorkerSemConexao`.
  Campos: `evento_id`, `pedido_id`, `chave_idempotencia`, `tentativa`,
  `particao`, `offset`, `atraso_fila_ms`, `duracao_ms`, `espera_ms`.
* **`OffsetCommitIgnorado` é o commit recusado por rebalance**
  (`ILLEGAL_GENERATION`/`REBALANCE_IN_PROGRESS`), não uma falha: a partição já
  tem outro dono e quem confirma o offset é ele. Sai em INFO; só
  `OffsetCommitFalhou` é ERROR.
* **Métricas** (`core.messaging.metricas`): contadores por processo
  (`recebidas`, `processadas`, `duplicadas`, `falhas`, `reentregas`, `dlq`,
  `invalidas`).
* **Healthchecks**: Kafka (`kafka-topics --bootstrap-server … --list`),
  Redis (`redis-cli ping`), API/worker com `restart: unless-stopped`; o
  RabbitMQ mantém `rabbitmq-diagnostics -q ping` no profile alternativo.
* **Análise agregada do log**: `scripts/measure_messaging.py --analisar-logs
  <arquivo>` resume o JSONL em contagem de eventos, distribuição de
  `duracao_ms`/`atraso_fila_ms`/`espera_ms` e distribuição de trabalho por
  instância **e por partição** (é o que evidencia a partição-por-consumidor).
* **Idempotência sob replay** (o teste que vale a pena): o grupo
  `synapseshop-pedidos` foi movido para `earliest` e as 4.120 mensagens da
  retenção foram relidas — 4.064 foram reconhecidas como `PedidoDuplicado` e o
  banco ficou **idêntico** (`processado = 4996`, `falha = 24` antes e depois).
  * **O reset exige o grupo parado**: com consumidores no grupo o comando
    `declarar_topicos_kafka --resetar-offsets` reporta sucesso e não move o
    offset — o consumidor já tem a posição em memória e segue dela. Pare o
    grupo, resete, suba de novo, e **confirme o offset** em
    `declarar_topicos_kafka --json`.
  * Replay de um histórico que contenha `X-Simular-Falha` **repopula a DLQ**,
    porque `simular_falha` está no banco e a falha injetada roda de novo.
* **Estado do broker**: `manage.py declarar_topicos_kafka --json` devolve
  tópicos, retenção efetiva, e por consumer group o estado, membros e
  `commit`/`lag` por partição.

## 11. Compatibilidade

* Esta é a **versão 1** do contrato. Mudanças incompatíveis exigem `versao = 2` e uma estratégia de migração (consumidores v1 devem rejeitar v2 com DLQ — conforme regra 5). Mudanças compatíveis (adicionar campos opcionais) podem manter a versão, mas devem ser documentadas aqui.