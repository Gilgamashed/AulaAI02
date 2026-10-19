# Apache Kafka: partições, offsets e DLQ (Aula 10)

> Conteúdo extraído do README.md (registro da aula). O README mantém apenas o resumo e o link para aqui.

## Apache Kafka: partições, offsets e DLQ (Aula 10)

A Aula 9 provou o fluxo assíncrono sobre **RabbitMQ** e mediu latência. A Aula 10
trocou o broker: agora a implementação é **Apache Kafka**, que é o que a spec
pede, e a topologia é a do Kafka (tópico + partições + offsets confirmados), não a
equivalência AMQP. RabbitMQ continua disponível por profile para comparação.

### O que mudou em relação à Aula 9

| Item da spec                                | Como está implementado no Kafka                              |
| ------------------------------------------- | ------------------------------------------------------------ |
| Tópico e partições para paralelismo         | `pedidos.criados` com **3 partições**, chave = `str(pedido.pk)` |
| Retenção configurável                       | `retention.ms` por tópico (7 dias no principal, 30 dias na DLQ) |
| Consumidor com `ack` manual                 | `enable.auto.commit=false` + `commit()` **depois** do efeito  |
| `acks=all` / publisher confirm              | `acks=all`, `enable.idempotence=true`, `flush()` antes do 201 |
| Consumer group (partição por consumidor)    | `synapseshop-pedidos` — cada membro fica dono de uma partição |
| Dead letter                                 | tópico terminal `pedidos.criados.dlq`, sem consumidor         |
| Backoff escalonado                          | tópicos `pedidos.criados.retry.1/2/3` com retenção 610/630/690 s |

Duas decisões que valem registro:

* **A chave de produção é o `pedido_id`.** Assim todos os eventos do mesmo pedido
  caem na mesma partição, e a ordem dos eventos de um pedido é preservada — a
  garantia que a partição dá em vez de dar ordem global.
* **O replayer usa tópico de retenção, não `sleep`.** O degrau de espera é o
  `retention.ms` do tópico de retry: a mensagem fica lá pelo tempo do backoff e
  some sozinha. Não há timer no worker, então reiniciar o worker não reinicia a
  espera. Um `sleep(45)` seria mais simples e perderia a mensagem se o processo
  morresse.

### Como as medições foram feitas

```powershell
# com 1 consumidor
docker compose up -d
.venv\Scripts\python.exe scripts\measure_messaging.py --purgar --pedidos 20 `
    --duplicatas 3 --forcar-falha 1 --carga 60 --concorrencia 8 --inspecionar-dlq

# com 3 consumidores concorrentes
docker compose up -d --scale worker-kafka=3
.venv\Scripts\python.exe scripts\measure_messaging.py --purgar --pedidos 20 `
    --duplicatas 3 --forcar-falha 1 --carga 60 --concorrencia 8 --inspecionar-dlq

# estado do broker: tópicos, retenção, offsets confirmados e lag por partição
docker compose exec api python api/manage.py declarar_topicos_kafka --json

# resumo do log transacional (não precisa da API no ar)
docker compose logs --no-color --no-log-prefix worker-kafka > logs_worker.jsonl
.venv\Scripts\python.exe scripts\measure_messaging.py --analisar-logs logs_worker.jsonl
```

`scripts/measure_messaging.py` detecta o broker em `/health` e troca só as etapas
de broker: no Kafka elas delegam aos management commands (o cliente Python do
broker só existe na imagem da API), no RabbitMQ leem a management API. Latência,
carga e análise de log são o mesmo código nos dois casos.

Quatro regras metodológicas que mudam o número final:

- **`DRF_USER_RATE` precisa estar no mesmo comando do `docker compose up`.**
  O `docker-compose.yml` injeta `${DRF_USER_RATE:-100/min}`; sem a variável no
  ambiente, qualquer `up` posterior recria a API no padrão. Ver "Defeitos de
  medição encontrados".
- **A latência é medida por *polling*** (`GET /pedidos/{id}`), com intervalo
  de 0,2 s no primeiro ciclo. Em fluxo feliz a latência é da ordem de dezenas de
  milissegundos, ou seja, do mesmo tamanho do intervalo — o número honesto é
  "dezenas de ms", não o valor exato.
- **O `--carga` do script mede a vazão do *pipeline inteiro*, e ele é limitado
  pelo POST.** O `GET /pedidos/{id}` custa ~0,8 s nesta pilha (DRF + banco), e
  o `POST` com `acks=all` espera o disco do broker. Uma carga de 30 pedidos com
  8 em paralelo mede 9,3 ped/s na publicação — e esse teto é da API, não da
  mensageria.
- **A vazão do *consumidor* tem que ser medida pelos timestamps do log do
  worker**, não pelo relógio de um script — ver a seção de paralelismo abaixo.

### Latência (ponta a ponta, com 1 consumidor)

Medida em repouso, sem carga, com 10 pedidos:

| Métrica                                   | valor                            |
| ----------------------------------------- | -------------------------------- |
| Latência publicação → `processado`        | média **152 ms**, p50 **100 ms**, p95 640 ms |
| POST (inclui o `acks=all` do broker)      | média 162 ms, p95 659 ms         |
| `POST /pedidos/` sob carga (n = 30)       | média 761 ms, p95 967 ms          |
| Idempotência (2 reenvios da mesma chave)  | 200, mesmo `id`, `duplicado: true` |
| Respostas 429 absorvidas                 | 0                                |

O POST custa mais que a latência do pipeline inteiro: ele espera o
`acks=all`, que é fsync no disco do broker, e é essa espera que o cliente sente.
Já a fila assíncrona entrega em milissegundos depois disso.

### Vazão e paralelismo: 1 versus 3 consumidores

O número vem dos **timestamps do log do worker**: a vazão é a distância entre a
primeira e a última `MensagemRecebida` de *uma* rajada, identificada pelo
prefixo da `chave_idempotencia`. Nenhum relógio de script entra na conta.

> **Por que não cronometrar de fora.** A primeira versão media o drain com um
> script que lia o offset confirmado do grupo, e o número estava **errado por
> construção**: dividia a soma *acumulada* dos offsets das 3 partições pelo tempo
> (`ultimo/dt`), um valor que cresce a cada rodada. Pior, o relógio começava
> quando o script subia — e o worker começa a drenar no instante em que entra no
> grupo, então numa rajada de 600 o script leu a linha de base **530 mensagens
> depois** do início e reportou 0,3 msg/s para um drain que já tinha terminado.
> O log do worker não sofre desse erro: o instante de cada mensagem é o registro
> do próprio broker, e a rajada é identificada sem ambiguidade.

Método: publica-se uma rajada com o worker **parado** (600 pedidos), sobe-se o
worker, e mede-se o span da rajada no log. As duas pernas foram executadas
encostadas, na mesma sessão e com a mesma imagem.

| Rajada de 600 mensagens        | 1 consumidor | 3 consumidores |
| ------------------------------ | ------------ | -------------- |
| Span da rajada no log         | **8,53 s**   | **9,68 s**     |
| Vazão                          | **70,2 msg/s**| **61,9 msg/s** |
| `duracao_ms` p50 / p95         | 10,7 / 31,3 ms | 9,6 / 45,6 ms |
| Mensagens por partição         | 197/188/215  | 195/200/205    |
| Processadas duas vezes         | 0            | 0              |
| `OffsetCommitFalhou`           | 0            | 0              |

**3 consumidores foram mais lentos que 1** (61,9 contra 70,2 msg/s, −12%), e não
3× mais rápidos. A partição-por-consumidor funciona — as 600 mensagens se
distribuem pelas 3 partições (195/200/205) e nenhuma é processada duas vezes —
mas **nesta configuração o paralelismo não paga**.

O motivo provável é o custo fixo de cada consumidor novo entrar no grupo: com 3
containers o grupo precisa coordenar 3 rebalances, e o `duracao_ms` máximo da
rajada sobe de 114 ms para **2.881 ms** — quase 3 s em que uma partição ficou
parada esperando o rebalance. Em uma rajada de 8,5 s, esses segundos fixos
comem o ganho do paralelismo. Soma-se a isso o commit síncrono por mensagem
(medido direto contra o broker: p50 1,30 ms, p95 2,59 ms; o mesmo lote sem
commit vai de 408 para 1017 msg/s), que serializa no broker e não paraleliza.

> **Registro honesto:** a primeira medição desta tabela dio 167 → 223 msg/s
> (ganho de 1,33×) e a conclusão "o broker single-node satura a 227% de CPU".
> **Os dois números estavam errados** — o primeiro pela divisão do offset
> acumulado, o segundo porque o `docker stats` foi amostrado **depois** do drain
> já ter terminado. A tabela acima é a medição corrigida.

> **Só 3 consumidores podem trabalhar.** `pedidos.criados` tem 3 partições, e o
> broker entrega cada partição inteira a um membro só. Com `--scale
> worker-kafka=5`, dois containers entram no grupo, não recebem partição e ficam
> ociosos gastando memória. Para mais paralelismo é preciso aumentar as
> partições do tópico — e isso **não pode ser feito depois**: Kafka só aceita
> aumentar, nunca reduzir.

### Onde está o gargalo

Do log transacional da rajada de 1 consumidor (600 mensagens):

| Métrica do log                        | média   | p50     | p95     |
| ------------------------------------ | ------- | ------- | ------- |
| `duracao_ms` (trabalho no consumidor) | 13,9 ms | 10,7 ms | 31,3 ms  |

Cada mensagem consome **~14 ms** de trabalho, dos quais ~1,3 ms são o commit
síncrono — **~10% do tempo**. O `atraso_fila_ms` alto na rajada é proposital: 600
pedidos publicados antes de o worker subir, para haver o que drenar. Não é
latência de sistema.

### Idempotência × latência × throughput

Os três requisitos puxam em direções opostas, e o desenho escolhe posição:

| Decisão                                | Ganho                                        | Custo                                        |
| -------------------------------------- | -------------------------------------------- | -------------------------------------------- |
| Dedupe no Redis antes do efeito        | evita transação e `UPDATE` no banco         | 1 ida e volta ao Redis por mensagem (~1 ms)  |
| Dedupe **só** no banco (`UPDATE` cond.)| dispensa o Redis no caminho crítico          | transação no banco para toda mensagem         |
| Backoff 5/15/45 s em retenção de tópico | não trava o consumidor com retentativa      | falha terminal demora ~65 s para ser visível |
| 1 mensagem por `poll()`                | processamento por mensagem isolado           | 1 consumidor processa 1 por vez               |
| `acks=all` + `enable.idempotence`      | nenhum 201 "fantasma"                        | POST espera o disco do broker                 |

O que a medição mostra é que **a idempotência é barata** (uma ida e volta ao
Redis, ~1 ms de um total de ~10 ms de trabalho no consumidor) e que **o custo
real da consistência está em esperar o resultado durável antes de responder
201** — se a API respondesse antes do confirm, o POST cairia para ~1 ms e o
cliente passaria a correr o risco de um pedido que nunca existiu.

### Dedupe fail-open: Redis fora do ar

Com `docker compose stop redis`, e o pipeline inteiro ainda funcionando:

| Métrica                        | Redis no ar | Redis fora do ar |
| ------------------------------ | ----------- | ---------------- |
| Pedidos processados            | 10/10       | 10/10            |
| Latência média                 | ~70 ms      | **3.437 ms**     |
| Idempotência (3 reenvios)      | 200, mesmo id | 200, mesmo id   |
| Eventos de degradação          | —           | `DedupeDegradado`, `DedupeNaoConfirmado` |

O comportamento é o desejado: **a janela do Redis é otimização, o banco é a
autoridade**. Com o Redis fora, o consumidor registra
`DedupeDegradado: "fail-open: o UPDATE condicional no banco continua
garantindo o efeito único"` e segue; o `UPDATE` condicional do PostgreSQL
continua impede qualquer efeito duplicado (os 3 reenvios devolveram o mesmo
pedido, sem novo evento). O preço é a **latência**: cada mensagem espera o
time-out do Redis (resolução de nome, ~1,7 s, duas vezes por mensagem) antes de
seguir. Fail-open compra disponibilidade ao preço da latência — que é
exatamente a escolha que a spec pedia para medir.

> O experimento acima é anterior ao contador `dedupe_degradado`, então a
> evidência dele são os eventos de log. Hoje a mesma degradação também aparece
> como número no snapshot do `WorkerEncerrado` — dá para responder "quantas
> vezes a janela não pôde ser usada" sem contar warnings.

### At-least-once: worker morto e rebalance

No Kafka, a garantia é a mesma da Aula 9 mas o nome muda: `basic_ack()` vira
`commit(message=…)`, e o que antes era "a fila devolveu" agora é "a partição
voltou para o grupo". O efeito no banco é gravado antes do commit, então uma
queda entre os dois devolve a mensagem em vez de perdê-la.

Três cenários medidos:

| Cenário                                                  | Resultado |
| -------------------------------------------------------- | --------- |
| `docker compose stop worker-kafka` no meio da rajada      | offset confirmado alcançou a marca d'água, **lag final 0** |
| `--scale worker-kafka=3` → `--scale worker-kafka=1` durante consumo | rebalance com partições mudando de dono; **0 `OffsetCommitFalhou`** |
| `docker compose kill -s KILL worker-kafka`                | offset volta ao último confirmado; sem perda |

O caso do rebalance mereceu uma correção de código. Ao mudar o número de
consumidores durante o consumo, o broker invalida a `generation_id` e recusa o
commit em voo com `ILLEGAL_GENERATION` — o comportamento **documentado** do
protocolo, porque a partição já tem outro dono e quem confirma o offset é ele.
Ainda assim o log registrava isso como ERROR vermelho a cada rebalance, parecendo
defeito no consumer. Hoje `_confirmar()` distingue os dois casos: rebalance sai
como `OffsetCommitIgnorado` em INFO com o motivo explícito, e só falha real de
commit continua em ERROR (`OffsetCommitFalhou`). Depois da correção, a rodada
com rebalance forçado no meio do consumo deu **0** falhas.

### Reset de offset: reprocessar o histórico

`manage.py declarar_topicos_kafka --resetar-offsets` volta o grupo para
`earliest` (ou `latest`), que é a operação que não existe em AMQP:

```powershell
# o grupo precisa estar VAZIO, senão o comando nao faz nada (ver abaixo)
docker compose stop worker-kafka
docker compose exec api python api/manage.py declarar_topicos_kafka `
    --resetar-offsets earliest --grupo synapseshop-pedidos
docker compose up -d worker-kafka
```

> **O reset só vale com o grupo parado.** Com o worker no ar o comando **retorna
> sucesso e não move nada**: o broker aceita o `AlterOffsets` para um grupo
> estável, mas o consumidor já tem a posição em memória e segue dela. Medido
> aqui: com 3 workers no grupo, o reset reportou `-> earliest` e os offsets
> continuaram no fim do log (1379/1355/1386 = watermark), com zero mensagens
> reprocessadas. Parando o grupo, o mesmo comando derrubou os três offsets para
> 0 (4120 mensagens pendentes) e o replay aconteceu de fato. **Always confira o
> offset depois do reset** — `declarar_topicos_kafka --json` mostra
> `commit`/`lag` por partição.

**Replay validado de ponta a ponta.** Depois do reset com o grupo vazio, o worker
releu as 4120 mensagens da retenção:

| Evento durante o replay                     | Quantidade |
| ------------------------------------------- | ---------- |
| `MensagemRecebida`                          | 4.135      |
| `PedidoDuplicado` (idempotência segurou)    | 4.064      |
| `PedidoFalha` / `PedidoDlq`                 | 57 / 14    |

E o banco **não mudou nada**: `processado = 4996` e `falha = 24` antes e depois,
idênticos. É a prova de que o efeito é único mesmo com o histórico inteiro
reprocessado — o dedupe no Redis e o `UPDATE` condicional no banco absorveram.

Um detalhe que vale registrar: os `PedidoFalha`/`PedidoDlq` do replay **não são
defeito**. São os pedidos de E2E criados com `X-Simular-Falha`, que guardam
`simular_falha=True` no banco — ao serem relidos, o consumer levanta a falha
injetada de novo e a escada roda outra vez. O replay de um histórico que
contém falhas intencionais **repopula a DLQ** (aqui, de 6 para 20 mensagens).
Com um histórico só de sucesso, o replay é 100% `PedidoDuplicado`.

### Logs transacionais

O consumer e o produtor emitem **um JSON por evento** (logger `core.messaging`),
com campos estruturados que tornam a análise uma agregação, não um `grep`:

```json
{"timestamp": "2026-10-01T16:07:41.882Z", "level": "INFO", "logger": "core.messaging",
 "evento": "PedidoProcessado", "resultado": "ok", "evento_id": "574b5cd4-...",
 "chave_idempotencia": "aula10-carga-1790873-14", "pedido_id": 336,
 "fila": "pedidos.criados", "tentativa": 0, "atraso_fila_ms": 17.0, "duracao_ms": 8.87,
 "mensagem": "pedido processado"}
{"timestamp": "...", "level": "WARNING", "logger": "core.messaging",
 "evento": "DedupeDegradado", "resultado": "erro",
 "motivo": "fail-open: o UPDATE condicional no banco continua garantindo o efeito único",
 "erro": "ConnectionError: Error -2 connecting to redis:6379. Name or service not known.",
 "mensagem": "janela de deduplicação indisponível; seguindo sem ela"}
```

`--analisar-logs` agrega o arquivo em contagem de eventos, distribuição de
`duracao_ms`/`atraso_fila_ms`/`espera_ms`, trabalho por instância e **por
partição** (é o que produz o 114/96/90 acima). O pacote de mensageria emite
**45 tipos de evento**, e a lista foi conferida contra o código com um grep de
`"evento":` — não é contagem de memória:

| Grupo                | Eventos                                                                                          |
| -------------------- | ------------------------------------------------------------------------------------------------ |
| Ciclo da mensagem    | `MensagemRecebida`, `MensagemEncerrada`, `PedidoProcessado`, `PedidoDuplicado`, `PedidoFalha`, `PedidoDlq`, `ErroConsumo` |
| Publicação           | `PedidoPublicado`, `PedidoPublicacaoFalhou`, `ProdutorCriado`, `ProdutorFechando`                |
| Topologia            | `TopicosDeclarados`, `TopicosDescritos`, `TopicosPurgados`, `OffsetsResetados`                    |
| Offset               | `OffsetCommitFalhou`, `OffsetCommitIgnorado`, `ReentregaFalhou`, `GruposIndisponiveis`            |
| Falha de política    | `DlqFalhou`, `PoliticaInconsistente`                                                              |
| Dedupe               | `DedupeDegradado`, `DedupeNaoConfirmado`, `DedupeNaoLiberado`                                     |
| Replay               | `ReplayerIniciado`, `ReplayerConectado`, `ReplayerEncerrando`, `ReplayerEncerrado`, `ReplayerErro`, `ReplayerFalha`, `RetryLiberada`, `RetryRetomado`, `RetryAguardando`, `RetrySemTimestamp`, `ReplayerTopicoDesconhecido`, `ReplayerPausaFalhou`, `ReplayerRetomadaFalhou`, `ReplayerDevolucaoFalhou` |
| Ciclo de vida worker | `WorkerIniciado`, `WorkerEncerrando`, `WorkerEncerrado`, `WorkerInterrompido`, `WorkerLimiteAtingido`, `WorkerParando`, `WorkerSemConexao` |
| Dispatcher           | `BrokerDesconhecido`                                                                              |

`PedidoCriado` **não** aparece nessa lista: é o nome do contrato
(`contracts.EVENTO_PEDIDO_CRIADO`), não um evento de log — o evento de
publicação que o produtor emite é `PedidoPublicado`.

### Defeitos de medição encontrados (e corrigidos)

Os problemas mais sérios desta aula não foram no sistema de mensageria — foram
**no próprio instrumento de medição**, e vale registrá-los porque é o que
transforma um relatório em evidência:

1. **A API grava `falha` antes de publicar na DLQ.** A medição original usava
   `sleep(2)` entre "API disse `falha`" e "ler a fila". Capturado com snapshots
   finos, o instante do `falha` é `t+68,1s` com `DLQ=0, retry.3=1` — a mensagem
   ainda estava na última fila de retry. Com o sleep, o relatório ora diria
   `dlq=0`, ora `dlq=1`. **Corrigido**: `aguardar_mensagem_na_dlq()` pergunta ao
   broker até a mensagem aparecer, e reporta quanto esperou (7,92 s na rodada
   com Kafka, porque a mensagem estava na retenção do degrau 3).
2. **Medir vazão pelo relógio do próprio script mede o script.** A primeira
   tentativa publicava uma rajada e ficava fazendo `GET /pedidos/{id}` a cada
   ~20 ms. Resultado: **1,0 ped/s** com 1 consumidor. O log do worker da mesma
   janela provava 20/s (gap p50 de **46 ms** entre mensagens processadas). O
   `GET` custa ~0,8 s nesta pilha, então o instrumento era mais lento que a
   coisa medida. **Corrigido**: a vazão do consumidor é medida pelo **offset
   confirmado do grupo**, que é número do broker.
3. **O gerador publicava mais do que pedia.** Com o loop de publicação contando
   a cada iteração em vez de a cada `N`, a primeira rajada pediu 60 e publicou
   64 — e o relatório dizia "64/60", o que denuncia a falha mas só depois de
   ela estar no número. **Corrigido**: o gerador guarda a contagem por lock e
   o alvo vem da marca d'água lida depois da publicação, nunca de um contador
   paralelo.
4. **O intervalo dinâmico do Windows tem só 1000 portas.** A carga roda dentro
   do container (`docker compose exec`), porque o host abre e fecha conexões
   para `localhost:8000` tão rápido que esgota `10000-10999` e falha com
   `WinError 10048`.
5. **Throttling absorvido em silêncio.** O `docker compose up --scale worker=3`
   recriou a API com `DRF_USER_RATE` no padrão (100/min) porque a variável não
   existia naquele shell. 11 respostas 429 empurraram a latência média da carga
   para **53 s**, contra ~4,5 s na rodada limpa — e o relatório saía limpo.
   **Corrigido**: todo 429 é contado, e a execução sai com código 1 e um aviso
   se passar de `--tolerar-429` (padrão 0).
6. **`RemoteDisconnected` não é `URLError`.** Derrubar a API no meio da carga
   matava o harness com traceback. **Corrigido**: `OSError`/
   `http.client.HTTPException` entram na mesma fila de retentativa, em contador
   separado do 429.
7. **Rebalance registrado como falha de commit.** `ILLEGAL_GENERATION` no
   commit durante `--scale` é o protocolo funcionando, não defeito. Detalhado
   em "At-least-once: worker morto e rebalance".

### Comandos úteis (Aulas 9 e 10)

```powershell
# Estado do broker: tópicos, retenção, offsets confirmados e lag por partição
docker compose exec api python api/manage.py declarar_topicos_kafka

# Verificar o que ficou preso na DLQ (lê sem consumir)
docker compose exec api python api/manage.py inspecionar_dlq_kafka

# Devolver as mensagens da DLQ ao tópico principal (ação destrutiva)
docker compose exec api python api/manage.py inspecionar_dlq_kafka --reprocessar

# Logs do worker
docker compose logs -f worker-kafka

# Escalar consumidores (o service não tem container_name de propósito)
docker compose up -d --scale worker-kafka=3

# Recuperar pedidos em pendente_publicacao
docker compose exec api python api/manage.py republicar_pedidos --dry-run
docker compose exec api python api/manage.py republicar_pedidos

# Medição completa (latência, idempotência, vazão, DLQ, offsets)
.venv\Scripts\python.exe scripts\measure_messaging.py --purgar --pedidos 20 `
    --duplicatas 3 --forcar-falha 1 --carga 60 --concorrencia 8 --inspecionar-dlq

# Só a vazão, sem esperar a escada de reentrega (~65 s)
.venv\Scripts\python.exe scripts\measure_messaging.py --purgar --pedidos 0 `
    --duplicatas 0 --forcar-falha 0 --carga 60 --concorrencia 8

# Resumo do log transacional
docker compose logs --no-color --no-log-prefix worker-kafka > logs_worker.jsonl
.venv\Scripts\python.exe scripts\measure_messaging.py --analisar-logs logs_worker.jsonl

# Dedupe degradado (fail-open)
docker compose stop redis
.venv\Scripts\python.exe scripts\measure_messaging.py --purgar --pedidos 10 --duplicatas 3
docker compose start redis

# RabbitMQ da Aula 9, por profile (a API precisa nascer com o mesmo broker)
$env:MENSAGERIA_BROKER='rabbitmq'
docker compose --profile rabbitmq up -d rabbitmq worker
```

### Recuperação quando o broker está fora

O `POST /pedidos/` **não depende do broker estar no ar**: se a publicação falha,
o pedido fica gravado com `status = pendente_publicacao` e a API responde
**503** com o motivo. Medido:

| Passo | Resultado |
| ----- | --------- |
| `docker compose stop kafka` e `POST /pedidos/` | **HTTP 503**, `status = pendente_publicacao` no banco |
| `docker compose start kafka` | broker volta |
| `manage.py republicar_pedidos` | pedido 2796 publicado em `pedidos.criados` (offset 592) |
| worker consome | `status = processado`, `tentativas = 1` |

Ou seja, o broker indisponível custa um **503 honesto e recuperável**, não um
pedido fantasma.

> Nota: o throttle é irrelevante para quem não mede, então **não** se elevou
> `DRF_USER_RATE` no `docker-compose.yml` — a medição eleva por variável de
> ambiente, no mesmo comando do `up`, e o harness se recusa a publicar números
> contaminados por 429.


