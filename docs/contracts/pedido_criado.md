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

O consumidor (`core.messaging.consumidor`) valida **estritamente** o payload com `core.messaging.contracts.validar_evento`:

1. **Tipo**: objeto JSON.
2. **Top-level**: `evento`, `versao`, `evento_id`, `idempotency_key`, `origem`, `ocorrido_em`, `publicado_em`, `pedido`.
3. **Pedido**: deve ser objeto com `id`, `usuario_id`, `status`, `total`, `itens` (lista não vazia).
4. **Itens**: cada item com `sku` não vazio, `quantidade` inteiro >= 1, `preco_unitario` decimal válido.
5. **Versão**: se `versao != 1` → `ContratoInvalido` → **DLQ imediata** (falha terminal; reentregar não conserta).
6. **Evento desconhecido**: diferente de `PedidoCriado` → `ContratoInvalido` → **DLQ**.

## 6. Publicação e entrega

* **Exchange**: `pedidos` (tipo `topic`), routing key `pedido.criado`.
* **Fila principal**: `pedidos.criados` (durável), DLX `pedidos.dlx` com routing key `pedido.criado` (fallback caso o consumidor rejeite sem routing key explícita).
* **Confirmações**: produtor usa **publisher confirms** (`channel.confirm_delivery()`). O POST só responde **201** depois do broker confirmar a publicação. Se a confirmação falhar, o pedido permanece em `status = pendente_publicacao` e a API responde **503** com instrução para executar `manage.py republicar_pedidos`.
* **Durabilidade**: exchanges e filas são duráveis; as mensagens são persistentes (padrão do `basic_publish` com `delivery_mode=2` implícito via persistência da fila).

## 7. Idempotência (ponta a ponta)

A chave viaja no evento e é usada em **duas barreiras**, independentes:

* **Barreira 1 — Redis (db 0), janela de idempotência**: `dedupe.reservar(evento)` faz `SET key NX EX ttl` (TTL configurável). Se a chave já existe → mensagem é **duplicata**: `ack` sem aplicar efeito, log `PedidoDuplicado`.
* **Barreira 2 — PostgreSQL**: `UPDATE` condicional com filtro `status__in(ESTADOS_PROCESSAVEIS)` **e** `idempotency_key = evento.idempotency_key`. Resultado 0 linhas:
  * se o pedido já está `processado` → duplicata real, log `PedidoDuplicado` (efeito já aplicado).
  * se a chave não confere com o pedido → `MensagemIncorreta` → **DLQ** (terminal).
  * se o pedido não existe → `MensagemIncorreta` → **DLQ**.

A janela do Redis evita reprocessar a mesma mensagem enquanto ela ainda está "em trânsito", e o UPDATE condicional é a autoridade final (garantia mesmo com Redis indisponível ou janela expirada).

## 8. Reentregas e DLQ

* **Tentativa inicial**: `tentativa = 0` (header AMQP **`x-tentativa`**, nome exato em `core.messaging.topologia.HEADER_TENTATIVA`; era `x-pedido-tentativa` em rascunhos antigos e foi corrigido para não duplicar o prefixo do app).
* **Backoff**: em caso de exceção recuperável, a mensagem é republicada para `pedidos.criados.retry.{d}` com TTL em segundos `5,15,45` (configuráveis via `.env`). Ao expirar o TTL, a fila de retry redireciona a mensagem de volta à fila principal (`x-dead-letter-exchange: pedidos`, `x-dead-letter-routing-key: pedido.criado`), com o header de tentativa incrementado.
* **Escada**: `max_reentregas = 3` → até 3 reentregas após a tentativa inicial (total de 4 passagens). Configurado por `PEDIDO_MAX_REENTREGAS` e `PEDIDO_BACKOFF_SEGUNDOS`.
* **DLQ**: se `tentativa >= max_reentregas` **OU** política inconsistente (faltam degraus) **OU** `ContratoInvalido` **OU** `MensagemIncorreta` → a mensagem é enviada para `pedidos.criados.dlq` (exchange `pedidos.dlx`, routing key `pedido.criado`) e o consumidor faz `ack`. Quando vai para DLQ por tentativas esgotadas, o pedido é marcado como `status = falha` e `motivo_falha` registra a última exceção (truncada a 200 caracteres).

### Dois contadores de tentativa (e por que os dois existem)

A mensagem que chega à DLQ carrega **dois** contadores, e eles não são
redundantes:

| Header        | Quem escreve                                                  | O que conta                                                                 |
| ------------- | ------------------------------------------------------------- | -------------------------------------------------------------------------- |
| `x-tentativa` | **a aplicação**, a cada republicação (`com_tentativa`)          | quantas vezes a aplicação escolheu reentregar                               |
| `x-death`     | **o próprio RabbitMQ**, a cada expiração de TTL                | quantas vezes a mensagem passou por uma fila com TTL (uma por degrau)       |

Medição real da mensagem retida na DLQ (leitura sem consumo pela management
API, `ack_requeue_true`):

```json
{
  "x-tentativa": 3,
  "x-motivo": "FalhaInjetada: falha injetada (X-Simular-Falha): pedido marcado para falhar",
  "x-death": [
    {"count": 1, "exchange": "pedidos.retry", "queue": "pedidos.criados.retry.3", "reason": "expired", "routing-keys": ["retry.3"]},
    {"count": 1, "exchange": "pedidos.retry", "queue": "pedidos.criados.retry.2", "reason": "expired", "routing-keys": ["retry.2"]},
    {"count": 1, "exchange": "pedidos.retry", "queue": "pedidos.criados.retry.1", "reason": "expired", "routing-keys": ["retry.1"]}
  ]
}
```

`x-tentativa = 3` (as três reentregas que a aplicação pediu) e três entradas de
`x-death` com `reason: expired` (as três filas de retry por onde a mensagem
expirou de fato) — 1 tentativa inicial + 3 reentregas = 4 passagens, como
projeta `PEDIDO_MAX_REENTREGAS=3`. O `x-death` é gerado pelo broker, então
serve de **auditoria independente**: se algum dia a aplicação errar o
`x-tentativa`, a diferença entre os dois contadores denuncia.

> O bloco acima é o header AMQP cru. O `--inspecionar-dlq` do
> `scripts/measure_messaging.py` resume as mesmas entradas em
> `{"fila", "motivo", "contagem", "trocada_por"}` (o `trocada_por` é o `exchange`
> desta linha), na ordem inversa — primeiro o degrau mais recente. Os números
> batem: `x_tentativa: 3` e três degraus `retry.3/retry.2/retry.1` com
> `motivo: expired`.

A **DLQ é terminal por construção**: declarada sem `x-message-ttl` e **sem**
`x-dead-letter-exchange`, para que a mensagem fique retida para inspeção (e
reenfile manual) em vez de sumir ou de voltar para a escada.

## 9. Simulação de falha (validação)

Para provar a escada ponta a ponta sem introduzir bugs artificiais no código de negócio, o POST aceita o header `X-Simular-Falha: 1` **somente** quando `PEDIDO_PERMITIR_SIMULACAO_FALHA` for verdadeiro (padrão `true` em desenvolvimento). Esse flag é gravado em `Pedido.simular_falha` e **lido do banco pelo consumidor**: ao processar o evento, se `simular_falha` for `True`, o consumidor levanta `FalhaInjetada` (exceção recuperável), forçando a reentrega até esgotar a escada e terminar na DLQ.

## 10. Observabilidade

* **Logs JSON** (`core.messaging`): eventos `MensagemRecebida`, `PedidoDuplicado`, `PedidoProcessado`, `PedidoFalha`, `PedidoDlq`, `PedidoPublicado`, `PedidoPublicacaoFalhou`, `TopologiaDeclarada`, `ReentregaFalhou`, `DedupeDegradado`, `MensagemEncerrada`, `WorkerIniciado`, `WorkerEncerrado`, `WorkerInterrompido`, `WorkerParando`, `WorkerSemConexao`, `DlqFalhou`, com `evento_id`, `pedido_id`, `chave_idempotencia`, `tentativa`, `atraso_fila_ms`, `duracao_ms` (quando aplicável). Erros de exceção são serializados com o **tipo** junto da mensagem (`descrever()`), porque `str(erro)` vem vazio em várias exceções do Python — o campo `erro: ""` não serve para diagnosticar nada.
* **Métricas** (`core.messaging.metricas`): contadores por processo (`recebidas`, `processadas`, `duplicadas`, `falhas`, `reentregas`, `dlq`, `invalidas`).
* **Healthchecks**: RabbitMQ (`rabbitmq-diagnostics -q ping`), Redis (`redis-cli ping`) e API/worker com `restart: unless-stopped` no `docker-compose.yml`.
* **Análise agregada do log**: `scripts/measure_messaging.py --analisar-logs <arquivo>` resume o JSONL em contagem de eventos, distribuição de `duracao_ms`/`atraso_fila_ms` e distribuição de trabalho por instância de worker (é o que evidencia o round-robin entre consumidores concorrentes).

## 11. Compatibilidade

* Esta é a **versão 1** do contrato. Mudanças incompatíveis exigem `versao = 2` e uma estratégia de migração (consumidores v1 devem rejeitar v2 com DLQ — conforme regra 5). Mudanças compatíveis (adicionar campos opcionais) podem manter a versão, mas devem ser documentadas aqui.