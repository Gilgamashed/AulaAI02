# Mensageria assíncrona (Aula 9)

> Conteúdo extraído do README.md (registro da aula). O README mantém apenas o resumo e o link para aqui.

## Mensageria assíncrona (Aula 9)

A Aula 9 introduz o **processamento assíncrono por eventos** para o fluxo de
pedidos. A API deixa de esperar o processamento terminar: cria o pedido,
publica o evento `PedidoCriado` com publisher confirms e responde **201**. Um
**worker** independente consome e avança o estado para `processado` (ou `falha`),
com **idempotência ponta a ponta** e **DLQ** para falhas irrecuperáveis.

O broker da Aula 9 é o **RabbitMQ**, e ele continua no projeto como
implementação alternativa (profile `rabbitmq`). A Aula 10 troca o padrão para
o **Kafka** — ver "Apache Kafka: partições, offsets e DLQ (Aula 10)". A escolha é
feita por uma variável de ambiente:

```powershell
# Kafka (padrão)
docker compose up -d

# RabbitMQ da Aula 9
$env:MENSAGERIA_BROKER='rabbitmq'
docker compose --profile rabbitmq up -d rabbitmq worker
```

O dispatcher (`core/messaging/broker.py`) é o único ponto que sabe qual é o
broker: a view, o worker e o replayer pedem "publique"/"consuma" e nunca citam
Kafka ou RabbitMQ. É o que permite as duas implantações rodarem com o mesmo
código Django, models e migrações — sem duplicar ORM.

### Ambiente: os dois conjuntos de serviços

| Serviço        | Imagem                             | Função                                                    |
| -------------- | ---------------------------------- | --------------------------------------------------------- |
| `kafka`        | `apache/kafka:3.9.1`               | Broker Kafka em KRaft single-node. Listener interno `kafka:29092`, externo `localhost:9092`. |
| `worker-kafka` | build do Dockerfile                | Consumidor Kafka + replayer de retry. Sobe após `api` e `kafka` saudáveis. |
| `rabbitmq`     | `rabbitmq:3.13-management-alpine`  | Broker AMQP 0-9-1 (profile `rabbitmq`), UI em `http://localhost:15672`. |
| `worker`       | build do Dockerfile                | Consumidor RabbitMQ (profile `rabbitmq`). |

Os volumes `kafkadata` e `rabbitmqdata` mantêm os dados se o container reiniciar.

Os serviços de worker **não** têm `container_name` de propósito: é o que permite
`docker compose up -d --scale worker-kafka=3` (um `container_name` fixo impede
escalar, porque o segundo container não teria nome livre).

A API **não** declara `depends_on` do broker: ela sobe com ou sem mensageria,
porque o pedido precisa ser gravado mesmo quando o broker está fora (ver
"Recuperação quando o broker está fora"). Quem depende do broker é o worker.

### Contrato do evento `PedidoCriado` (v1)

O evento é definido em [`docs/contracts/pedido_criado.md`](../contracts/pedido_criado.md). Campos mínimos de negócio, `idempotency_key`, `publicado_em` (epoch ms) e valores monetários como **string** (evita perda de precisão com Decimal em JSON).

Exemplo resumido:

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

Validação estrita no consumidor: payload inválido → **DLQ imediata** (falha terminal).

### Idempotência (duas barreiras)

A chave viaja no evento e é usada em **duas camadas independentes**:

1. **Janela de idempotência (Redis db 0)** — `core/messaging/dedupe.py`. Usa `SET key NX EX ttl` (TTL 86.400 s, configurável por `DEDUPE_TTL_SEGUNDOS`). `reservar()` retorna `False` se a chave já existe → mensagem duplicada, `ack` sem aplicar efeito. Em caso de falha do Redis, o código é **fail-open** (processa e deixa o banco proteger). No caminho de falha, `liberar()` apaga a chave para que a reentrega consiga reprocessar.
2. **Update condicional (PostgreSQL)** — no consumidor: `UPDATE Pedido SET status='processado', ... WHERE pk=? AND idempotency_key=? AND status IN (pendente_publicacao,pendente,falha)`. Se 0 linhas afetadas: (a) já `processado` → duplicata real (log `PedidoDuplicado`, motivo "pedido já estava processado"); (b) chave diferente ou pedido inexistente → `MensagemIncorreta` → **DLQ** (terminal). Esta é a **autoridade final** (sobrevive mesmo com TTL expirado ou Redis indisponível).

A chave de idempotência no POST segue precedência: **header `Idempotency-Key`** (se <=64) ou **SHA-256 canônico** (usuário + itens ordenados por SKU + total). Um reenvio com a mesma chave devolve **HTTP 200** com `"evento": {"duplicado": true, "motivo": "pedido já existente"}` (ou 409 se o corpo for diferente).

### Reentregas, backoff e DLQ

Topologia declarada por `core/messaging/topologia.py`:

```
exchange pedidos (topic) --routing key pedido.criado--> pedidos.criados
                                                         │ DLX pedidos.dlx
exchange pedidos.retry (direct) --retry.1/.2/.3--------> pedidos.criados.retry.N (TTL 5/15/45 s)
                                                         │ DLX pedidos (volta à principal)
exchange pedidos.dlx (direct)   --pedido.criado--------> pedidos.criados.dlq (terminal, sem TTL)
```

Política:

- Tentativa inicial = 0 (header **`x-tentativa`**). Em exceção recuperável, republica para retry `{tentativa+1}` com TTL e `ack` da original.
- **3 reentregas** após a inicial (total até 4 passagens). Configurável por `PEDIDO_MAX_REENTREGAS` e `PEDIDO_BACKOFF_SEGUNDOS` (5,15,45).
- Ao esgotar (`tentativa >= max_reentregas`) ou em falha terminal (`ContratoInvalido`, `MensagemIncorreta`, política inconsistente), o pedido é marcado como `status = falha`, a mensagem vai para `pedidos.criados.dlq` e é `ack` — **nunca** reentregada infinitamente.

**Simulação de falha (validação ponta a ponta):** `POST /pedidos/` aceita `X-Simular-Falha: 1` **somente** se `PEDIDO_PERMITIR_SIMULACAO_FALHA=true`. O flag é gravado em `Pedido.simular_falha` e lido **do banco** pelo consumidor: ao processar, se verdadeiro, levanta `FalhaInjetada` (exceção recuperável), forçando a escada completa até a DLQ. Isso prova, com um pedido real e logs por tentativa, que a política de backoff e a DLQ funcionam conforme o desenho.

### Recuperação de publicações falhas

Se o broker estiver indisponível no momento do POST, o `publish` levanta `PublicacaoFalhou` (inclusive para `OSError`/DNS — evita virar 500). A view responde **HTTP 503** com corpo contendo `pedido_id`, `status: pendente_publicacao`, `idempotency_key` e o erro. O comando `python api/manage.py republicar_pedidos` varre pedidos em `pendente_publicacao`, republica seus eventos (publisher confirms) e, só depois do confirm, move-os para `pendente`. Também aceita `--pedido`, `--limit`, `--dry-run`. O idempotente: reenviar o POST com a mesma `Idempotency-Key` enquanto o broker está fora devolve **HTTP 200** com `evento.duplicado = true` e o pedido permanece em `pendente_publicacao`.

### Observabilidade (comum aos dois brokers)

- **Logs JSON** (logger `core.messaging`): a lista completa de eventos está na
  seção da Aula 10 (45 tipos) e em `docs/contracts/pedido_criado.md`; os campos
  são `evento_id`, `pedido_id`, `chave_idempotencia`, `tentativa`,
  `atraso_fila_ms`, `duracao_ms` (e `particao`/`offset`/`espera_ms` no Kafka).
- **Métricas em memória** (`core.messaging.metricas`): `recebidas`, `processadas`, `duplicadas`, `falhas`, `reentregas`, `dlq`, `invalidas`.
- **Medição ponta a ponta**: `scripts/measure_messaging.py` (stdlib) faz POST autenticado com `Idempotency-Key` explícita, aguarda `processado` por polling com intervalo adaptativo e reporta: latência **POST** (publisher confirm) e **publicação→processado** (baseada em `evento.publicado_em`), idempotência (3 reenvios), escada de reentrega com timestamps por tentativa, e profundidade das filas via Management API (`:15672`). Usa sessão JWT com renovação automática e pode `--purgar` as filas antes da medição.

**Medições reais (execução local, 20 pedidos + idempotência + DLQ):**

| Métrica | n | média | p50 | p95 | máx |
|---|---|---|---|---|---|
| POST (publisher confirm) | 20 | 78,83 ms | — | 101,76 ms | 105,45 ms |
| publicação → processado | 20 | 82,35 ms | 75 ms | 124 ms | 172 ms |

**Idempotência:** 3 reenvios com a mesma `Idempotency-Key` → **HTTP 200**, mesmo `pedido_id`, `evento.duplicado = true` (idempotente).

**Escada de reentrega (X-Simular-Falha):** tentativas registradas em `t+0,0s` (tentativa 0→1), `t+6,1s` (1→2), `t+21,3s` (2→3), `t+66,8s` (3→DLQ) — correspondendo aos degraus **5 s / 15 s / 45 s**. Pedido terminou em `status=falha`, mensagem na `pedidos.criados.dlq`. Após a leitura, as filas ficaram: `pedidos.criados.dlq` com 1 mensagem pronta (evidência da DLQ) e as demais vazias.

> Esses dois blocos de medições são da **Aula 9 (RabbitMQ)** e ficam aqui como
> linha de base. A Aula 10 repetiu a medição no Kafka, e os números do Kafka são
> os da seção seguinte — as duas tecnologias não são diretamente comparáveis
> linha a linha porque a topologia, a latência de confirmação e o mecanismo de
> reentrega são diferentes por desenho.


