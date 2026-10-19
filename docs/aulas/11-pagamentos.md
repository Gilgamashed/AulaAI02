# Pagamento, notificação e o segundo fluxo Kafka (Aula 11)

> Conteúdo extraído do README.md (registro da aula). O README mantém apenas o resumo e o link para aqui.

## Pagamento, notificação e o segundo fluxo Kafka (Aula 11)

O DoD da Aula 11 é um caminho de três passos: **criar pedido ➔ simular pagamento
➔ notificar**. O que a aula acrescenta não é o caminho — é que o pagamento é
**outro fluxo de eventos**, com tópico, grupo, offsets, retries e DLQ próprios.

```
POST /pedidos/            POST /pedidos/{id}/pagamento/     worker-pagamentos
      │                            │                                │
      ▼                            ▼                                ▼
pedidos.criados          pagamentos.registrados            UPDATE condicional
      │                            │                    (pagamento.status) +
      │                            │                    INSERT notificacao
      ▼                            │                                │
worker-kafka                           │                                │
      │                            │                                │
UPDATE pedido.status  ──► notificado_em preenchido ◄────────────────────┘
```

O `worker-kafka` continua tratando só de pedidos e o `worker-pagamentos` só de
pagamentos. Nenhum dos dois enxerga o tópico do outro.

### Por que dois fluxos e não dois tipos de evento no mesmo tópico

Poderia ser `pedidos.criados` com dois tipos de evento. Não é, e a razão é
operacional:

| Se fosse o mesmo tópico | O que acontece |
| ------------------------ | -------------- |
| Um consumidor só | processa pedido **e** pagamento; o worker de pagamento nunca roda |
| Dois consumidores | as partições são **disputadas**: cada worker lê metade dos eventos do outro fluxo, e metade dos pedidos não é processada por quem deveria |
| Uma DLQ só | "o que está preso?" exige inspecionar os dois fluxos para responder |

Com tópicos separados, cada fluxo tem consumidor, paralelismo
(`KAFKA_PARTICOES_PAGAMENTOS`), offset, dedupe e DLQ próprios — e o `--fluxo`
dos comandos de administração diz qual dos dois você está olhando.

O que os dois fluxos **compartilham** é a política de reentrega (`5,15,45 s`,
máximo 3) e o replayer. Estado, não é.

### Subir o ambiente

```powershell
# 1. sobe API + os dois workers + kafka, redis, db e inventory
docker compose up -d --build

# 2. cria a topologia dos DOIS fluxos (idempotente: pode repetir).
#    Precisa da API no ar: o comando roda dentro do container `api`.
docker compose exec api python api/manage.py declarar_topicos_kafka

# 3. confere que os dois fluxos estão de pé
curl.exe http://localhost:8000/health
```

```powershell
# estado do broker de um fluxo por vez
docker compose exec api python api/manage.py declarar_topicos_kafka --fluxo pagamentos --json
docker compose exec api python api/manage.py inspecionar_dlq_kafka --fluxo pagamentos
```

Os sete serviços do Compose: `api`, `inventory`, `worker-kafka`,
`worker-pagamentos`, `kafka`, `db` e `redis`. O RabbitMQ continua como profile
alternativo da Aula 9 e serve **apenas** ao fluxo de pedidos.

### A flag de falha injetada (leia antes de demonstrar a DLQ)

`PEDIDO_PERMITIR_SIMULACAO_FALHA` e `PAGAMENTO_PERMITIR_SIMULACAO_FALHA` estão
ligadas (`true`) por padrão no Compose, e as duas são consultadas **pela API**: a
view decide se aceita o header `X-Simular-Falha` e grava `simular_falha` no
registro. O worker não lê flag nenhuma: ele honra a marcação gravada no banco.

Com a flag desligada o header é **ignorado em silêncio** (o POST segue normal e
`simular_falha` fica `false`), que é o comportamento correto fora de
desenvolvimento: um cliente não deve poder sabotar o próprio pedido.

Os dois interruptores são separados porque a falha injetada leva a mensagem para
a **DLQ do seu fluxo**. Misturar as duas sabotagens no mesmo interruptor
tornaria "qual fluxo parou?" mais difícil de responder do que precisava.

### Endpoints novos

| Método | Rota | Quem | Devolve |
| ------ | ---- | ---- | ------- |
| `POST` | `/api/v1/pedidos/{id}/pagamento/` | dono do pedido | **201** com o pagamento em `registrado` e o bloco `evento` (tópico, partição, offset) |
| `GET` | `/api/v1/pedidos/{id}/pagamento/` | dono ou admin | o pagamento, com o desfecho que o **worker** gravou |
| `GET` | `/api/v1/notificacoes/` | dono (só as suas) ou admin (todas) | lista paginada, filtrável por `pedido` e `canal` |

Matriz de permissões da notificação:

| Verbo | Anônimo | user | admin |
| ----- | -------- | ---- | ----- |
| `GET /notificacoes/` | 401 | só as do próprio pedido | todas |

O corpo do `POST` decide o **método** e o **desfecho** do gateway simulado:
`metodo` (`pix`, `cartao_credito`, `boleto`), `aprovado`, `motivo_recusa`
(**obrigatório** quando `aprovado` é `false`, proibido quando é `true`) e
`canal` (`email`, `sms`, `push`; padrão `email`).

### O `status` do pagamento não muda na API

O `POST` responde `201` com `status: registrado` e o bloco `evento`. Esse
`registrado` é estado **local do produtor** — a linha foi criada e o evento foi
confirmado pelo broker. Quem vira `aprovado`/`recusado` é o worker, aplicando o
efeito do evento; é por isso que a transição é um `UPDATE` **condicional** no
worker, e não um `UPDATE` na API (que deixaria o `UPDATE` condicional sem linhas
para casar e a notificação nunca seria criada).

Então, logo depois do `POST`, um `GET` ainda devolve `registrado` — isso é o
funcionamento normal, não uma falha:

> **As barras invertidas no `-d` não são um erro de digitação.** No PowerShell
> 5.1, `-d '{"metodo": "pix"}'` chega na API como `{metodo: pix}` e a resposta é
> `JSON parse error`. As aspas duplas dentro de um argumento de executável nativo
> precisam ser escapadas (`\"`), como nos exemplos abaixo. Alternativas que não
> precisam de escape: `--%` (stop-parsing) ou `Invoke-RestMethod` com `-Body`.

```powershell
# 1. paga
curl.exe -X POST http://localhost:8000/api/v1/pedidos/5120/pagamento/ `
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" `
  -d '{\"metodo\": \"pix\", \"aprovado\": true, \"canal\": \"email\"}'
# {"status":"registrado", ..., "evento":{"topico":"pagamentos.registrados","fluxo":"pagamentos","chave":"5120","particao":1,"offset":1}}

# 2. alguns segundos depois, o worker aplicou o efeito
curl.exe http://localhost:8000/api/v1/pedidos/5120/pagamento/ -H "Authorization: Bearer $TOKEN"
# {"status":"aprovado", "aprovado":true, "notificado_em":"2026-...", ...}
```

Medido nesta aula (pedido 5120, `R$ 699.30`, PIX, canal email):

| Passo | Resultado |
| ----- | --------- |
| `POST /pedidos/` | `201`, `status=processado` (worker-kafka), total `699.30` |
| `POST /pedidos/5120/pagamento/` | `201`, `status=registrado`, `evento.chave=5120` (o **`pedido_id`**, não o `pagamento_id`) |
| ~7 s depois, `GET` do pagamento | `status=aprovado`, `notificado_em` preenchido |
| `GET /notificacoes/?pedido=5120` | `count: 1` — *"Seu pagamento de R$ 699.30 via PIX foi aprovado."* |

E o caminho da recusa (pedido 5121, `R$ 899.10`, cartão de crédito, SMS):
`status=recusado`, uma notificação, *"Seu pagamento de R$ 899.10 via cartão de
crédito foi recusado: saldo insuficiente"*, no canal `sms`.

### Re-POST: mesma tentativa republica, outra tentativa é 409

`Pagamento.pedido` é `OneToOne` — um pedido aceita **um** pagamento. O re-POST
bate no `IntegrityError` do banco, e quem decide o que responder é a
`idempotency_key` (SHA-256 de **pedido + método + desfecho**), não o
`IntegrityError`, que só diz que *já existe algum pagamento*:

| Re-POST | Resposta | Porquê |
| ------- | -------- | ------ |
| mesmo método, mesmo desfecho, ainda `registrado` | `200`, `republicado: true` | a cura do `503`: republica o evento perdido |
| mesmo método, mesmo desfecho, já resolvido | `200`, `republicado: false`, `evento.duplicado: true` | o gateway já respondeu; publicar de novo criaria uma **segunda** notificação para um fato já notificado |
| **método ou desfecho diferente** | **`409`** + `pagamento_existente` | é outra tentativa, e o `OneToOne` a impede |
| `aprovado: false` sem `motivo_recusa` | `400` | a coerência do desfecho é validada **na entrada** |

O `409` é o caso que dá sentido aos outros: sem comparar a chave, um `POST` com
`metodo: "boleto"` contra um pedido já pago com PIX devolvia `200` e o
pagamento em PIX — o cliente recebia um "deu certo" para um pedido que não
tentou fazer.

### Idempotência sob reentrega e replay

Três barreiras, nesta ordem: janela no **Redis** (`SET NX EX`), `UPDATE`
condicional no **PostgreSQL** e unicidade de `Notificacao.pagamento` (`OneToOne`).
A chave de dedupe é prefixada pelo nome do fluxo, então pagamento e pedido não
colidem.

Medido: cinco cópias do mesmo `PagamentoRegistrado` republicadas produziram
**uma** notificação. O Redis descartou as duplicatas; apagando a key do Redis à
mão, foi o `UPDATE` condicional que descartou — e a contagem continuou em 1, com
o pagamento inalterado.

### Falha injetada, escada e DLQ deste fluxo

```powershell
curl.exe -X POST http://localhost:8000/api/v1/pedidos/5124/pagamento/ `
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" `
  -H "X-Simular-Falha: 1" -d '{\"metodo\": \"pix\", \"aprovado\": true}'

# em outro terminal
docker compose logs -f worker-pagamentos
```

O header grava `simular_falha` no pagamento (**não** viaja no evento: o worker
lê do banco) e o consumidor levanta `FalhaInjetada`, uma exceção recuperável.
O que esperar:

| Momento | Banco | Log |
| ------- | ----- | ---- |
| t = 0 | `status=registrado`, `tentativas=1` | `PagamentoFalha`, `motivo: reentrega 1/3 em 5s` |
| t ≈ 6 s | `tentativas=2` | `PagamentoFalha`, `reentrega 2/3 em 15s` |
| t ≈ 22 s | `tentativas=3` | `PagamentoFalha`, `reentrega 3/3 em 45s` |
| t ≈ 67 s | `tentativas=4`, **sem notificação** | `PagamentoDlq` |

Os intervalos entre as mensagens medidos foram 6,7 s e 16,3 s para backoffs
declarados de 5 s e 15 s — a espera acontece **no tópico**, não num `sleep` do
worker.

Repare que **não existe** `status = falha` no `Pagamento`: o pedido continua
`processado`, e quem continua pendente é o **aviso**, que não foi criado.

Reprocessar a DLQ:

```powershell
# inspecionar sem consumir
docker compose exec api python api/manage.py inspecionar_dlq_kafka --fluxo pagamentos

# devolver ao tópico principal
docker compose exec api python api/manage.py inspecionar_dlq_kafka --fluxo pagamentos --reprocessar
```

O `--reprocessar` **descarta o `x-tentativa`** que veio da DLQ. Sem esse
reset, a mensagem volta com a escada já esgotada: o worker a processa uma vez e
a manda direto de volta para a DLQ, enquanto o comando reporta "1 mensagem
devolvida ao tópico principal". O sintoma — uma mensagem na DLQ que ninguém
colocou lá — não aponta para o header. O `x-motivo` também sai: ele descreve a
falha **daquela** tentativa.

> **"vazia" no `inspecionar` não significa "topico vazio".** As duas coisas
> medem coisas diferentes, e depois de um `--reprocessar` elas discordam de forma
> que parece bug:
>
> | Onde | O que mede | Situação depois de reprocessar as 4 mensagens |
> | ---- | ---------- | ------------------------------------------- |
> | `inspecionar_dlq_kafka` | o que o **grupo de inspeção** ainda não tratou (`synapseshop-dlq-inspecao-<fluxo>`) | `vazia` — o `--reprocessar` confirmou o offset, então não há o que ler |
> | `declarar_topicos_kafka --json` | o que o **tópico** ainda retém (`mensagens`) | `4` — o tópico é append-only |
>
> Reprocessar **devolve** a mensagem ao tópico principal; ela não sai da DLQ.
> Como a retenção da DLQ é de 30 dias, as 4 mensagens ficam lá até expirarem.

Medido: pedido 5115 com `X-Simular-Falha`, escada esgotada, `simular_falha`
limpo no banco e evento reprocessado — o worker aprovou, criou **uma**
notificação e a DLQ ficou vazia.

### Observabilidade dos dois fluxos

O `/health` devolve a **topologia completa** de cada fluxo em `fluxos` (tópico,
grupo, partições, retenção, tópico de DLQ, grupo de replay, a escada de
`topicos_retry` e `max_reentregas`):

```powershell
curl.exe http://localhost:8000/health
```

Agrupar por fluxo continua valendo, mas o detalhe não pode sumir: quem depura
pagamento precisa do estado do fluxo de pagamento, e o `/health` é a rota que
responde antes de qualquer outra quando algo trava.

O que o `/health` **não** traz é `lag`, offset confirmado e contagem de DLQ, e
isso é deliberado: o Compose o usa como `healthcheck` do container, então ler os
watermarks dos tópicos a cada sondagem transformaria o endpoint de liveness em
carga no broker. Para o estado que se move:

```powershell
# offsets, lag e tamanho da DLQ de um fluxo
docker compose exec api python api/manage.py declarar_topicos_kafka --fluxo pagamentos --json

# só a DLQ
docker compose exec api python api/manage.py inspecionar_dlq_kafka --fluxo pagamentos
```

Campos de log que só existem **por** haver dois fluxos: `fluxo` (qual stream a
linha veio — é o que permite filtrar `worker-kafka` e `worker-pagamentos` com o
mesmo `grep`) e `pagamento_id`. `pedido_id` sozinho não identifica a entidade:
um pagamento e um pedido de mesmo número coexistem. Os eventos de log do fluxo
ganham o prefixo `Pagamento` (`PagamentoProcessado`, `PagamentoDuplicado`,
`PagamentoFalha`, `PagamentoDlq`, `PagamentoPublicado`,
`PagamentoPublicacaoFalhou`); o laço de consumo é o mesmo dos dois fluxos.

### O que **não** foi feito (Anti-Hallucination)

A spec é explícita sobre não antecipar as aulas seguintes, e nada abaixo entrou:

* **nenhum** teste automatizado e **nenhuma** pipeline de CI/CD;
* **nenhum** dashboard ou extração de dados (o `Notificacao` foi modelado
  pensando nisso, mas é isso: uma tabela com índice, não um relatório);
* **nenhuma** IA, recomendação ou integração com serviço externo;
* o RabbitMQ **não** ganhou o segundo fluxo — implementá-lo exigiria uma
  topologia AMQP equivalente, e fingir que os dois brokers têm a mesma coisa
  seria mentir sobre a assimetria.

### Ficheiros da aula

* Contrato do evento: [`docs/contracts/pagamento_registrado.md`](../contracts/pagamento_registrado.md)
* Coleção Postman (21 requests, na ordem do DoD): [`collections/synapseshop_aula11.postman_collection.json`](../../collections/synapseshop_aula11.postman_collection.json)


