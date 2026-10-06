# Contrato `PagamentoRegistrado` — versão 1

Segundo evento de domínio do SynapseShop, publicado pela API quando o gateway
de pagamento simulado responde ao `POST /api/v1/pedidos/{id}/pagamento/`. É a
mesma fronteira entre projeto síncrono (API) e projeto assíncrono (worker) que
o `PedidoCriado` abriu na Aula 9 — com uma diferença que é o ponto da Aula 11:
este evento mora em **outro fluxo**, com tópico, grupo, offsets, retries e DLQ
próprios.

*Versão*: `1`
*Evento*: `PagamentoRegistrado`
*Origem*: `synapseshop-api`

## 1. Por que este evento é um fluxo separado

O `PedidoCriado` e o `PagamentoRegistrado` poderiam ser dois tipos de evento
dentro do mesmo tópico `pedidos.criados`. Não são, e a escolha é operacional,
não estética:

* **Consumidores diferentes.** `worker-kafka` processa pedidos,
  `worker-pagamentos` processa pagamentos. Se dividissem o tópico, as partições
  seriam disputadas entre os dois e cada worker leria metade dos eventos do
  outro fluxo.
* **Eixo de paralelismo próprio.** `KAFKA_PARTICOES_PAGAMENTOS` permite
  escalar o fluxo de pagamento sem mexer no de pedidos.
* **Isolamento de falha.** Uma DLQ de pagamento não contém pedidos, então
  "o que está preso?" tem uma resposta que não depende de inspecionar os dois
  fluxos.
* **Offset e dedupe independentes.** Replay do histórico de pedidos não
  reescreve o estado de pagamentos, e vice-versa.

Os dois fluxos **compartilham** a mesma política de reentrega
(`5,15,45 s`, máximo 3) e o mesmo replayer, porque o comportamento-idêntico é
o que permite reusar o código; o que não é compartilhado é estado.

## 2. O corpo do evento

Payload real, gerado por `contracts.construir_pagamento_registrado` para o
pagamento 2 (pedido 5112, recusado por cartão):

```json
{
  "evento": "PagamentoRegistrado",
  "versao": 1,
  "evento_id": "dadf6bbe-7da5-4cae-aae3-4ede4d9bc6ce",
  "idempotency_key": "ee53e8d1c0b3bb3bd2eadca4f8c22f67980d8623fa025a7e9b9bfbc50a9d4b0f",
  "origem": "synapseshop-api",
  "ocorrido_em": "2026-10-06T00:35:29.783Z",
  "publicado_em": 1791246929783,
  "pagamento": {
    "id": 2,
    "pedido_id": 5112,
    "usuario_id": 2,
    "status": "recusado",
    "metodo": "cartao_credito",
    "valor": "399.60",
    "aprovado": false,
    "motivo_recusa": "saldo insuficiente",
    "canal_notificacao": "sms"
  }
}
```

## 3. Campos e regras

| Campo | Tipo | Obrigatório | Notas |
|---|---|---|---|
| `evento` | `string` | Sim | Deve ser `"PagamentoRegistrado"`. |
| `versao` | `integer` | Sim | Contrato v1: `1`. Versão diferente → `ContratoInvalido` (terminal, DLQ). |
| `evento_id` | `string` (UUID v4) | Sim | Identificador único do evento; liga a linha do log do produtor à do consumidor. |
| `idempotency_key` | `string` (hex/64) | Sim | SHA-256 de **(pedido_id, método, desfecho)**, calculada pelo servidor. Fecha a barreira no worker. |
| `origem` | `string` | Sim | `"synapseshop-api"`. |
| `ocorrido_em` | `string` (ISO-8601 UTC) | Sim | Instante do fato. |
| `publicado_em` | `integer` (epoch ms) | Sim | Relógio do produtor; base do `atraso_fila_ms`. |
| `pagamento.id` | `integer` | Sim | PK do pagamento (o consumidor atualiza por este ID). |
| `pagamento.pedido_id` | `integer` | Sim | Pedido cobrado. É também a **chave Kafka** da mensagem. |
| `pagamento.usuario_id` | `integer` | Sim | Dono do pedido; permite filtrar notificações por dono no worker. |
| `pagamento.status` | `string` | Sim | **`aprovado` ou `recusado`** — e tem que concordar com `aprovado`. Ver abaixo. |
| `pagamento.metodo` | `string` | Sim | `pix`, `cartao_credito` ou `boleto`. |
| `pagamento.valor` | `string` (decimal) | Sim | **Sempre string.** Snapshot de `Pedido.total` no momento da tentativa. |
| `pagamento.aprovado` | `boolean` | Sim | Desfecho que o gateway simulado respondeu. |
| `pagamento.motivo_recusa` | `string` | Condicional | **Obrigatório** quando `aprovado` é `false`; proibido quando é `true`. |
| `pagamento.canal_notificacao` | `string` | Não (padrão `email`) | `email` ou `sms`. Ver a decisão abaixo. |

### `status` no evento: por que nunca `registrado`

`Pagamento.status` tem três valores no banco: `registrado`, `aprovado`,
`recusado`. E o evento **só carrega os dois últimos**.

`registrado` é estado **local do produtor**: significa "a linha foi criada e o
evento ainda não foi publicado". Ele descreve a transação da API, não o
desfecho do gateway, e é por isso que o `INSERT` grava `registrado` e quem
faz a transição para `aprovado`/`recusado` é o **worker**, no efeito do evento.
Se a API fizesse esse `UPDATE`, o `UPDATE` condicional do worker não encontraria
mais as linhas processáveis e a notificação nunca seria criada.

O contrato reforça isso com uma validação cruzada
(`contracts.validar_pagamento_registrado`): `status` precisa ser exatamente
`aprovado` se `aprovado` é `true`, e `recusado` se é `false`. Publicar
`status: "registrado"` com `aprovado: true` é um evento que **mente sobre o
próprio desfecho**, e a razão para recusá-lo no contrato, e não no consumidor,
é que um payload recusado aparece no log com a explicação; um payload aceito
aparece no relatório como "aprovado, mas registrado para sempre", que é muito
mais difícil de diagnosticar.

### Decisão de modelagem: `canal_notificacao` é transitório

`canal_notificacao` **não** é coluna de `Pagamento`. Ele existe só entre a
publicação e o worker, e quem o persiste é a `Notificacao`, criada pelo worker —
porque quem decide o texto e o canal do aviso é quem **cria** o aviso.

Isso explica um detalhe de leitura: o `GET` do pagamento não devolve
`canal_notificacao`, e a resposta de criar pagamento também não. Para saber de
que canal o cliente foi avisado, o caminho é a notificação.

O texto da notificação ("Pagamento aprovado", "Seu pagamento de R$ 799.20 via
PIX foi aprovado.") **não é contrato**. Ele é apresentação, muda com o idioma da
aula, e fica em `api/core/notificacoes.py` justamente para não viajar no evento.

## 4. Serialização

* Corpo em JSON UTF-8, sem BOM.
* Números monetários como strings (`Decimal` não é JSON; `float` perde
  precisão).
* `publicado_em` é `int` (epoch milissegundos).
* `evento_id` é UUID v4, gerado no produtor.

## 5. Validação e tratamento de erros

O consumidor chama `contracts.validar(corpo)`, que roteia por
`corpo["evento"]` para `validar_pagamento_registrado`. Assim o mesmo laço de
consumo atende aos dois contratos sem um `if` por tipo de evento em cada etapa.

1. **Tipo**: objeto JSON.
2. **Top-level**: `evento`, `versao`, `evento_id`, `idempotency_key`, `origem`,
   `ocorrido_em`, `publicado_em`, `pagamento`.
3. **Pagamento**: objeto com `id`, `pedido_id`, `usuario_id`, `status`,
   `metodo`, `valor`, `aprovado`.
4. **Coerência do desfecho** (as três regras que não são "campo ausente"):
   * `aprovado: false` **sem** `motivo_recusa` → inválido. Sem motivo não há o
     que notificar ao cliente.
   * `aprovado: true` **com** `motivo_recusa` → inválido. O desfecho e o motivo
     precisam concordar.
   * `status` incompatível com `aprovado` → inválido.
5. **Versão**: `versao != 1` → `ContratoInvalido` → **DLQ imediata**.
6. **Evento desconhecido** → `ContratoInvalido` → **DLQ**.

### O evento valida, mas o efeito é recusado

`contracts.validar` roteia pelo campo `evento` do corpo, e
`validar_pagamento_registrado` aceita tanto `PedidoCriado` quanto
`PagamentoRegistrado` — qualquer um dos dois é um contrato v1 **bem formado**.
Por isso, logo antes de aplicar o efeito, o worker checa se o evento pertence
ao seu fluxo: publicar um `PedidoCriado` em `pagamentos.registrados` é
rejeitado com `MensagemIncorreta` e a mensagem vai para a DLQ **de
pagamentos**.

Validar sempre contra o contrato do fluxo do worker pareceria mais limpo, e
seria pior: trocaria uma falha visível e localizada por um efeito aplicado no
lugar errado, sem erro nenhum. O contrato garante a forma; o worker garante o
destino.

As três regras de coerência também são aplicadas **na entrada**, em
`PagamentoSimularSerializer.validate`. É melhor um 400 explicando o que falta
do que um evento que o worker rejeitaria como DLQ por algo que o cliente podia
ter lido antes.

## 6. Publicação e entrega

* **Tópico principal**: `pagamentos.registrados`, com **3 partições**
  (`KAFKA_PARTICOES_PAGAMENTOS`).
* **Chave de produção**: `str(pagamento.pedido_id)` — **não** o `pagamento_id`.
  É a mesma razão do `PedidoCriado`: o Kafka garante ordem por key, então os
  dois eventos de um mesmo pedido nunca são lidos fora de ordem. E como o
  pagamento é `OneToOne`, `pagamento_id` e `pedido_id` são 1:1 na prática, mas
  a key é o que dá nome de negócio ao log de partitionamento e à ordenação.
* **Retenção**: `KAFKA_RETENCAO_MS` no principal, `KAFKA_RETENCAO_DLQ_MS`
  (30 dias) na DLQ.
* **Confirmações**: `acks=all` com `enable.idempotence=true` e `flush()` antes
  da resposta. O POST só responde **201** depois do broker confirmar.
* **Consumo**: `enable.auto.commit=false` e `enable.auto.offset.store=false`; o
  offset é confirmado **depois** do efeito aplicado.
* **Producer singleton** por processo, reaproveitado entre os dois fluxos.

### Recuperação de publicação falha: o próprio endpoint

Se o broker não confirmar, o pagamento fica em `status = registrado` e a API
responde **503**. A cura é **reenviar o mesmo POST**, e não um comando de
recuperação como o `republicar_pedidos` da Aula 9. A chave de idempotência é
derivada de (pedido, método, desfecho), então o reenvio cai no `IntegrityError`
do `OneToOne` e é reconhecido como a mesma tentativa.

O `_republicar_pagamento` distingue os três casos pela **chave**:

| Situação | Resposta |
|---|---|
| mesma chave, ainda `registrado` | republica o evento, **200** com `republicado: true` |
| mesma chave, já resolvido | **200** com `republicado: false` e `evento.duplicado: true` |
| **chave diferente** (outro método ou outro desfecho) | **409**, com o pagamento existente no corpo |

O terceiro caso é o que justifica os outros dois: o `IntegrityError` só diz que
*este pedido já tem um pagamento*, não que ele é o pagamento que o cliente está
tentando criar. Sem comparar a chave, um `POST` com `metodo: "boleto"` contra um
pedido já pago com PIX devolvia **200** e o pagamento em PIX — o cliente
recebia um "deu certo" para um pedido que não tentou fazer.

## 7. Idempotência (ponta a ponta)

Duas barreiras independentes, com **chave própria do fluxo**: o dedupe é
prefixado pelo nome do fluxo (`chave_dedupe`), então uma chave de pagamento não
colide com uma de pedido mesmo que o SHA coincida.

* **Barreira 1 — Redis (db 0)**: `dedupe.reservar(evento)` faz `SET key NX EX
  ttl`. Chave existente → duplicata: confirma o offset sem aplicar efeito, log
  `PagamentoDuplicado`.
* **Barreira 2 — PostgreSQL**: `UPDATE` condicional filtrando por status
  processável **e** `idempotency_key`. 0 linhas:
  * pagamento já resolvido → duplicata real (`PagamentoDuplicado`);
  * chave não confere, ou pagamento não existe → `MensagemIncorreta` → **DLQ**
    (terminal).

A `Notificacao` é criada dentro da mesma transação do `UPDATE` condicional, com
chave única por `pagamento`. É a segunda barreira que garante o que a
validação manual mediu: **cinco republished do mesmo evento produziram uma
notificação só**.

Medição: com 5 cópias do mesmo `PagamentoRegistrado` republished, o Redis
descartou as duplicatas; apagando a key do Redis à mão, foi o `UPDATE`
condicional que descartou — e a contagem de notificações continuou em 1, com o
pagamento inalterado.

## 8. Reentregas e DLQ

A topologia é derivada do tópico base, sem constante nova:
`pagamentos.registrados.retry.{1,2,3}` e `pagamentos.registrados.dlq`.

* **Tentativa inicial**: `tentativa = 0` (header `x-tentativa`).
* **Escada**: máximo 3 reentregas (5 s, 15 s, 45 s). A espera acontece **no
  tópico** (retenção = degrau), com o replayer devolvendo ao principal quando o
  prazo vence — não há `sleep` no worker.
* **DLQ**: `tentativa >= max_reentregas`, ou política inconsistente, ou
  `ContratoInvalido`, ou `MensagemIncorreta` → `pagamentos.registrados.dlq`, e
  o offset é confirmado. Quando vai por tentativas esgotadas, o pagamento fica
  como está (não há `status = falha` no `Pagamento`: o pedido continua
  `processado`, e quem continua pendente é o **aviso**, que não foi criado).
* **`tentativas`** conta as passagens totais, então o valor final é 4, não 3.

### Replay da DLQ: o `x-tentativa` volta a zero

`manage.py inspecionar_dlq_kafka --fluxo pagamentos --reprocessar` devolve a
mensagem ao tópico principal e **descarta o `x-tentativa`** que veio da DLQ.

Isso não é detalhe: sem o reset, a mensagem volta com
`tentativa = max_reentregas`, o worker a processa **uma** vez e a manda
direto de volta para a DLQ. O comando reporta "1 mensagem devolvida ao tópico
principal" e a DLQ aparece com a mensagem de novo — sem que nada a tenha
colocado lá. O sintoma não aponta para o header, e o `--reprocessar` vira um
`--reprocessar` que não reprocessa.

O `x-motivo` também sai: ele descreve a falha **daquela** tentativa, e a
tentativa nova ainda não tem motivo.

Comportamento verificado: pedido 5115, pagamento marcado com
`X-Simular-Falha`; depois de esgotar a escada, `simular_falha` limpo no banco e
o evento reprocessado — o worker aprovou, criou **uma** notificação
(`status=aprovado`, `notificado_em` preenchido) e a DLQ ficou vazia.

## 9. Simulação de falha (validação)

O POST aceita o header `X-Simular-Falha: 1`, gravado em `Pagamento.simular_falha`
e **lido do banco pelo consumidor** (o valor não viaja no evento). Ao processar,
se `simular_falha` for `True`, o consumidor levanta `FalhaInjetada` (recuperável)
e a escada roda até a DLQ.

O interruptor é `PAGAMENTO_PERMITIR_SIMULACAO_FALHA`, e quem o consulta é a
**API** — em `PedidoViewSet._simular_falha_pagamento`, a mesma forma de
`PEDIDO_PERMITIR_SIMULACAO_FALHA`. O consumidor não lê flag nenhuma: ele honra
`simular_falha` gravado no banco. Desligada, a API **ignora o header em
silêncio**: `201` com `simular_falha=false`, a mensagem segue para o tópico
principal e a DLQ nunca recebe nada. É o comportamento correto fora de
desenvolvimento — um cliente não deve poder sabotar o próprio pagamento.

São duas flags, e não uma, porque a falha injetada leva a mensagem para a DLQ
**do fluxo de pagamento**. Misturar as duas sabotagens num interruptor só
tornaria "qual fluxo parou?" mais difícil de responder.

## 10. Observabilidade

* **Logs JSON** (`core.messaging`), com prefixo por fluxo: `PagamentoRecebido`
  não existe — o laço de consumo é o mesmo, e quem desambigua é a chave `fluxo`
  e o prefixo do log (`PagamentoProcessado`, `PagamentoDuplicado`,
  `PagamentoFalha`, `PagamentoDlq`, `PagamentoPublicado`,
  `PagamentoPublicacaoFalhou`, `DlqReprocessada`).
* **Campos que só existem por haver dois fluxos**: `fluxo` (qual stream a linha
  veio — é o que permite filtrar `worker-kafka` e `worker-pagamentos` com o
  mesmo `grep`) e `pagamento_id`. `pedido_id` sozinho não identifica a
  entidade: um pagamento e um pedido de mesmo número coexistem.
* **Sintaxe do relatório da DLQ**: a key do pagamento é o `pedido_id`, então o
  relatório mostra `pagamentos:5115` e não `pagamentos:5` — senão o número
  apontaria para a entidade errada.
* **Healthcheck**: `/health` devolve os **dois fluxos** em `fluxos`, e o detalhe
  não pode sumir: quem depura pagamento precisa do estado do fluxo de pagamento,
  e o `/health` é a rota que responde antes de qualquer outra coisa quando algo
  trava. O que ele traz é a **topologia** — `topico`, `grupo`, `particoes`,
  `retencao_ms`, `topico_dlq`, `grupo_replay`, `auto_offset_reset`, a escada de
  `topicos_retry` e `max_reentregas`. **Não** traz offset, lag nem contagem de
  DLQ: o Compose usa `/health` como `healthcheck` do container, e ler os
  watermarks dos tópicos a cada sondagem transformaria o endpoint de liveness em
  carga no broker. Para o estado que se move (`lag`, DLQ), o comando é
  `declarar_topicos_kafka --fluxo pagamentos --json` e
  `inspecionar_dlq_kafka --fluxo pagamentos`.
* **Estado do broker**: `manage.py declarar_topicos_kafka --fluxo pagamentos --json`.
  Vale saber que ele e `inspecionar_dlq_kafka` medem coisas diferentes: o `--json`
  conta as mensagens que o **tópico** ainda retém (`mensagens`), e o `inspecionar`
  conta o que o **grupo de inspeção** (`synapseshop-dlq-inspecao-pagamentos`) ainda
  não tratou. Depois de um `--reprocessar` as duas divergem — "vazia" no
  `inspecionar` com `mensagens: 4` no `--json` é o estado **correto**: o offset foi
  confirmado, e o tópico da DLQ é append-only (as mensagens só somem por
  expiração, em 30 dias).

## 11. Compatibilidade

* Versão **1**. Mudanças incompatíveis exigem `versao = 2` e estratégia de
  migração (consumidores v1 rejeitam v2 com DLQ). Adicionar campo **opcional**
  mantém a versão, desde que documentado aqui.
* O `status` é o campo mais frágil do contrato: ele é derivado de
  `aprovado` e validado contra ele. Se um dia o pagamento ganhar um quarto
  desfecho (ex.: `estornado`), é `versao = 2` — não um novo valor aceito em
  silêncio pela regra 3 da seção 5.