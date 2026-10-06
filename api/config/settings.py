import os
from datetime import timedelta
from pathlib import Path

import dj_database_url

BASE_DIR = Path(__file__).resolve().parent.parent

# Aula 7: SECRET_KEY passa a ser obrigatória em produção via variável de
# ambiente (DJANGO_SECRET_KEY no .env/docker-compose). O valor abaixo é
# APENAS fallback de desenvolvimento — nunca use em ambiente real.
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-insecure-synapseshop-key")

DEBUG = os.environ.get("DJANGO_DEBUG", "True") == "True"

ALLOWED_HOSTS = ["*"]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    # Aula 7: SimpleJWT (autenticação por tokens) e django-filter
    # (filtros declarativos nas listagens).
    "rest_framework_simplejwt",
    "django_filters",
    "core.apps.CoreConfig",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# Banco fornecido pelo serviço `db` do docker-compose via DATABASE_URL.
DATABASES = {
    "default": dj_database_url.config(
        default=os.environ.get(
            "DATABASE_URL",
            "postgresql://synapse:synapse@localhost:5432/synapse",
        )
    )
}

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]

LANGUAGE_CODE = "pt-br"

TIME_ZONE = "America/Sao_Paulo"

USE_I18N = True

USE_TZ = True

STATIC_URL = "static/"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# =====================================================================
# Aula 7 — Configuração do Django REST Framework
# =====================================================================
REST_FRAMEWORK = {
    # Autenticação: primária = JWT (Bearer token via SimpleJWT); a Session
    # fica habilitada para o Admin e a browsable API do DRF (não quebra o
    # fluxo original), mantendo o controle de acesso por token na API.
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ],
    # Padrão público (AllowAny): o catálogo é de leitura livre; cada
    # viewset combina permissões específicas sobre esse padrão (ver
    # core/permissions.py e core/views.py).
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.AllowAny",
    ],
    # Throttling (segurança mínima): taxas globais por anônimo e por usuário
    # autenticado; a rota de login ainda ganha um ScopedRateThrottle próprio
    # (scope "login") para conter força bruta (ver core/urls.py).
    "DEFAULT_THROTTLE_CLASSES": [
        # Aula 8: são as classes do DRF com o cache trocado pelo alias
        # "throttle" (em memória) — ver core/throttling.py. Mantidas as
        # mesmas taxas da Aula 7; o objetivo é apenas isolar o throttling
        # da disponibilidade do Redis (fail-open do cache-aside).
        "core.throttling.ThrottleMemoriaAnon",
        "core.throttling.ThrottleMemoriaUser",
    ],
    "DEFAULT_THROTTLE_RATES": {
        # Taxas da Aula 7, agora parametrizáveis por ambiente. Os padrões
        # abaixo são exatamente os originais (nenhuma mudança de contrato):
        # a Aula 8 só precisa de `DRF_ANON_RATE`/`DRF_USER_RATE` para medir
        # RPS sem que a própria medição vire um 429.
        "anon": os.environ.get("DRF_ANON_RATE", "20/min"),
        "user": os.environ.get("DRF_USER_RATE", "100/min"),
        "login": "5/min",
    },
    # Paginação global (PageNumberPagination) aplicada a TODAS as listagens
    # da API — os endpoints críticos ficam paginados por padrão.
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 20,
    # Filtros coerentes: django-filter (filterset declarativo p/ category,
    # is_active, faixa de preço) + busca livre (SearchFilter) + ordenação
    # por qualquer campo exposto (OrderingFilter).
    "DEFAULT_FILTER_BACKENDS": [
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.SearchFilter",
        "rest_framework.filters.OrderingFilter",
    ],
}

# =====================================================================
# Aula 7 — Configuração do SimpleJWT
# =====================================================================
SIMPLE_JWT = {
    # Access token de curta duração (minutos): limita a janela de uso caso
    # um token seja vazado; o refresh (1 dia) renova sem reautenticação.
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=5),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=1),
    "UPDATE_LAST_LOGIN": True,
    # Assinatura com chave própria (JWT_SIGNING_KEY) separada do SECRET_KEY
    # do Django. Se ausente no .env, usa o SECRET_KEY como fallback — nunca
    # um segredo hardcoded.
    "SIGNING_KEY": os.environ.get("JWT_SIGNING_KEY", SECRET_KEY),
}

# =====================================================================
# Aula 8 — Cache-aside com Redis
# =====================================================================
# URL do Redis. No compose o serviço `api` usa o host interno `redis`
# (injetado via REDIS_URL); o padrão abaixo serve ao Django rodando no
# venv local, onde o Redis está publicado em localhost:6379. Em produção
# a credencial (se houver) entra na própria URL: redis://:senha@host:6379/1.
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/1")

# Interruptor do cache-aside. CACHE_ENABLED=false ignora TODO o cache
# (nenhuma leitura/escrita no Redis) e é o switch usado para medir o
# desempenho "antes" do cache na Aula 8.
#
# A leitura é tolerante a caixa: `true`/`True`/`1`/`yes`/`on` ligam, e
# `false`/`0`/`no`/`off` desligam. Isso não é preciosismo — o compose
# interpola strings cruas, e uma comparação case-sensitive faria
# `CACHE_ENABLED=true` (minúsculo, como manda a convenção) ser ignorado em
# silêncio, mantendo o cache ligado numa suposta medição de baseline.
def _env_flag(nome: str, padrao: str) -> bool:
    return os.environ.get(nome, padrao).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


CACHE_ENABLED = _env_flag("CACHE_ENABLED", "True")

# Tempos de vida (TTL, em segundos) — valores sugeridos pela spec da Aula 8:
#   60s  para as LISTAGENS  (variam mais; o usuário tolera dados um pouco velhos)
#   300s para o DETALHE/consulta pesada (acesso direto a um registro)
# Ambos são apenas uma rede de segurança: a invalidação por evento de
# domínio (core/signals.py) é quem garante a correção dos dados.
CACHE_TTL_LIST = int(os.environ.get("CACHE_TTL_LIST", "60"))
CACHE_TTL_DETAIL = int(os.environ.get("CACHE_TTL_DETAIL", "300"))

# =====================================================================
# Aula 9 — Mensageria assíncrona com RabbitMQ
# =====================================================================
# Conexão AMQP. No compose, `api` e `worker` recebem a URL com o host
# interno do serviço `rabbitmq`; o padrão abaixo serve ao Django rodando
# no venv local (RabbitMQ publicado em localhost:5672).
#
# A senha vem do `.env` (RABBITMQ_PASSWORD) e nunca é versionada. Atenção:
# o usuário `guest` do RabbitMQ só pode se conectar de localhost — por isso
# o compose cria um usuário de aplicação (`RABBITMQ_USER`).
RABBITMQ_URL = os.environ.get(
    "RABBITMQ_URL", "amqp://synapse:synapse@localhost:5672/%2F"
)

# Topologia (nomes de exchange, filas e routing keys) fica em
# `core/messaging/topologia.py`; aqui ficam apenas os PARÂMETROS de política,
# porque são os que mudam entre ambientes (e os que a spec pede documentados).
PEDIDO_EXCHANGE = os.environ.get("PEDIDO_EXCHANGE", "pedidos")
PEDIDO_ROUTING_KEY = os.environ.get("PEDIDO_ROUTING_KEY", "pedido.criado")
PEDIDO_FILA = os.environ.get("PEDIDO_FILA", "pedidos.criados")
PEDIDO_FILA_DLQ = os.environ.get("PEDIDO_FILA_DLQ", "pedidos.criados.dlq")

# Política de reentrega: 1 tentativa inicial + até N reentregas, cada uma
# com um atraso próprio. A escada padrão (5s -> 15s -> 45s) é implementada
# por filas de retry com `x-message-ttl` + dead-letter de volta para a fila
# principal: o atraso acontece NO BROKER, então o worker não fica ocupado
# nem faz "busy loop" esperando.
#
# Ao esgotar a última reentrega, a mensagem vai para a DLQ. Um payload
# inválido (contrato quebrado) não consome a escada: vai direto para a DLQ,
# porque reentregar dez vezes um JSON malformado não o torna válido.
PEDIDO_MAX_REENTREGAS = int(os.environ.get("PEDIDO_MAX_REENTREGAS", "3"))
PEDIDO_BACKOFF_SEGUNDOS = tuple(
    int(segmento)
    for segmento in os.environ.get("PEDIDO_BACKOFF_SEGUNDOS", "5,15,45").split(",")
    if segmento.strip()
)

# TTL da chave de deduplicação. Precisa ser maior que o tempo total da
# escada de reentrega (5+15+45 = 65 s aqui) com folga, para que a chave não
# expire enquanto a mensagem ainda está em trânsito. Uma chave que dura
# pouco permite que uma duplicata atrasada volte a ser "primeira vez".
DEDUPE_TTL_SEGUNDOS = int(os.environ.get("DEDUPE_TTL_SEGUNDOS", "86400"))

# Interruptor da simulação de falha forçada (validação da DLQ). `true`
# apenas em desenvolvimento: liga o header `X-Simular-Falha`, que marca o
# pedido para o worker falhar de propósito. Em produção o header é ignorado.
PEDIDO_PERMITIR_SIMULACAO_FALHA = _env_flag("PEDIDO_PERMITIR_SIMULACAO_FALHA", "False")

# Se o produtor cair (RabbitMQ fora), o pedido nasce como
# `pendente_publicacao`, o POST responde 503 e o comando
# `republicar_pedidos` recupera o que ficou pendente. O caminho feliz é
# publicar logo após o commit e só então marcar o pedido como `pendente`.
PEDIDO_ESTADO_INICIAL = "pendente_publicacao"
PEDIDO_ESTADO_PUBLICADO = "pendente"

CACHES = {
    "default": {
        # Backend NATIVO do Django (>=4.0) sobre o cliente redis-py: já
        # speaks SETEX (TTL) e INCR (contador de geração da invalidação),
        # dispensando uma dependência extra como o django-redis.
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": REDIS_URL,
        # Prefixo aplicado a todas as chaves: isola o cache do SynapseShop
        # caso o mesmo Redis sirva a outros projetos (chave real no Redis:
        # "synapseshop:1:item:2:detalhes"). Nenhuma informação sensível.
        "KEY_PREFIX": "synapseshop",
        # Timeout padrão = TTL da listagem (menor dos dois, por serem chaves
        # mais voláteis e numerosas).
        "TIMEOUT": CACHE_TTL_LIST,
        "OPTIONS": {
            # Timeouts curtos: se o Redis travar, a API não pode ficar
            # esperando — o cache-aside cai para o banco (fail-open).
            "socket_connect_timeout": 1,
            "socket_timeout": 1,
        },
    },
    # Cache do throttling (ver `core/throttling.py`): fica em memória,
    # isolado da disponibilidade do Redis. Por rodar só neste processo, o
    # LOCATION é apenas um rótulo.
    "throttle": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "synapseshop-throttle",
    },
    # Aula 9: janela de deduplicação da mensageria. Fica em OUTRO banco do
    # mesmo Redis (db 0) de propósito: as chaves de dedupe são descartáveis
    # por TTL e não devem conviver com as chaves do cache-aside (que têm
    # invalidação por evento). Separar os bancos torna a auditoria trivial
    # (`redis-cli -n 0 keys 'dedupe:*'`) e permite zerar um sem o outro.
    "dedupe": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": os.environ.get("REDIS_URL_DEDUPE", "redis://localhost:6379/0"),
        "KEY_PREFIX": "synapseshop",
        "TIMEOUT": DEDUPE_TTL_SEGUNDOS,
        "OPTIONS": {
            # O dedupe é fail-open (ver `core/messaging/dedupe.py`): se o
            # Redis travar, o worker processa a mensagem e o UPDATE
            # condicional no banco segue sendo a garantia final de
            # idempotência. Portanto o timeout pode ser curto.
            "socket_connect_timeout": 1,
            "socket_timeout": 1,
        },
    },
}

# =====================================================================
# Aula 10 — Mensageria: Kafka (padrão) ou RabbitMQ
# =====================================================================
# Broker usado pelo produtor (dentro do processo da API) e pelo consumidor.
# O Kafka é o padrão da Aula 10; `rabbitmq` mantém a topologia da Aula 9
# disponível, sem código duplicado — a escolha acontece em
# `core/messaging/broker.py` e cada serviço do compose fixa o seu valor.
#
# Leitura tolerante a caixa (mesmo `_env_flag`): o compose interpola a string
# crua do `.env`, e `MENSAGERIA_BROKER=Kafka` ser ignorado em silêncio
# trocaria o broker sem nenhuma pista no log.
MENSAGERIA_BROKER = os.environ.get("MENSAGERIA_BROKER", "kafka").strip().lower()

# ---------------------------------------------------------------------
# Kafka
# ---------------------------------------------------------------------
# `bootstrap.servers`: a lista de brokers que o cliente usa para descobrir o
# resto do cluster. Duas URLs porque são **dois contextos**, e o cliente
# recebe a lista certa em cada um:
#   * dentro do compose (api, worker-kafka): `kafka:29092` (listener interno,
#     anunciado como o nome do serviço, que é resolvido na rede do compose);
#   * no venv local / script de medição: `localhost:9092` (listener externo,
#     anunciado como localhost, que é o que o host consegue alcançar).
# A ordem não importa: o librdkafka tenta todos e usa o que responder.
KAFKA_BOOTSTRAP_SERVERS = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")

# `client.id` padrão. Quem fala com Kafka é identificado por ele no
# `kafka-consumer-groups.sh --describe` e no log do broker — sem ele, um bug de
# produção vira "uma aplicação desconhecida está consumindo". O produtor e cada
# componente sobrescrevem com um sufixo próprio (ver `kafka_topologia`).
KAFKA_CLIENT_ID = os.environ.get("KAFKA_CLIENT_ID", "synapseshop")

# `acks=all`: o líder espera todas as ISR confirmarem. É o que permite dizer que
# a mensagem está durável antes de o POST responder 201.
KAFKA_ACKS = os.environ.get("KAFKA_ACKS", "all")

# `linger.ms`: agrupa publicações de janelas muito curtas em um round-trip ao
# broker. 5 ms é o que a documentação do librdkafka sugere como ponto de
# equilíbrio: abaixo disso o ganho é quase nulo, acima disso a latência do POST
# piora. A mediação da Aula 10 mede este efeito (ver README).
KAFKA_LINGER_MS = int(os.environ.get("KAFKA_LINGER_MS", "5"))

# `compression.type`. `none` é o padrão **de propósito**: a medição da Aula 10
# compara broker a broker, e ligar compressão mudaria o resultado por um motivo
# que não é o broker. Fica exposta para quem quiser medir esse eixo à parte.
KAFKA_COMPRESSAO = os.environ.get("KAFKA_COMPRESSAO", "none")

# Teto de espera pelo ACK (`delivery.timeout.ms`). Estourado, o cliente entrega
# um relatório de erro e o `kafka_produtor` transforma em 503 + pedido em
# `pendente_publicacao`. Alinhado com o timeout do socket para que a falha seja
# rápida e previsível.
KAFKA_TIMEOUT_ENVIO_MS = int(os.environ.get("KAFKA_TIMEOUT_ENVIO_MS", "5000"))
# O mesmo teto em segundos, usado no `flush()` (a API do librdkafka é em
# segundos, a config é em milissegundos; manter os dois em settings diferentes
# evitaria um erro de unidade silencioso).
KAFKA_TIMEOUT_ENVIO_S = KAFKA_TIMEOUT_ENVIO_MS / 1000.0

# Partições do tópico principal: é o eixo de paralelismo do consumo, e o número
# que a spec pede para medir (1 vs 3). NÃO pode ser alterado depois que o tópico
# existe — mudar a contagem re-mapeia a key para outra partição e a ordem por
# pedido se perde (ver a docstring de `kafka_topologia`).
KAFKA_PARTICOES = int(os.environ.get("KAFKA_PARTICOES", "3"))

# Réplicas. 1 porque o compose roda um broker único (KRaft sem quorum); em
# cluster real este é o número que evita ponto único de falha, e é por isso que
# ele é setting e não constante.
KAFKA_REPLICAS = int(os.environ.get("KAFKA_REPLICAS", "1"))

# `retention.ms` do tópico principal (7 dias) e da DLQ (30 dias). A DLQ dura
# mais porque é a única cópia de um evento que deu problema; o tópico principal
# dura o bastante para reproduzir a medição de throughput a partir do histórico.
KAFKA_RETENCAO_MS = int(os.environ.get("KAFKA_RETENCAO_MS", str(7 * 24 * 3600 * 1000)))
KAFKA_RETENCAO_DLQ_MS = int(
    os.environ.get("KAFKA_RETENCAO_DLQ_MS", str(30 * 24 * 3600 * 1000))
)

# Folga somada a `2 × degrau` na retenção de cada tópico de retry (ver
# `kafka_topologia.retencao_retry_ms`). No Kafka a retenção APAGA a mensagem —
# ao contrário do TTL do RabbitMQ, que a devolve —, então a retenção precisa
# cobrir o backoff com folga para o replayer poder estar reiniciado sem perder
# mensagem. 10 min é folga para restart, não um plano de retenção.
KAFKA_FOLGA_RETENCAO_RETRY_MS = int(
    os.environ.get("KAFKA_FOLGA_RETENCAO_RETRY_MS", str(10 * 60 * 1000))
)

# Tópicos. Os nomes são os mesmos das filas AMQP da Aula 9 de propósito: as
# duas bases precisam descrever o mesmo desenho para a comparação entre
# brokers ser justa (e o `measure_messaging.py` reaproveita as mesmas
# constantes).
KAFKA_TOPICO_PEDIDOS = os.environ.get("KAFKA_TOPICO_PEDIDOS", "pedidos.criados")
KAFKA_TOPICO_DLQ = os.environ.get("KAFKA_TOPICO_DLQ", "pedidos.criados.dlq")

# Grupo do consumidor principal. É a identidade que carrega o offset: trocar o
# nome (ou o `group.id`) faz o consumidor recomeçar do começo, o que é o
# mecanismo do teste de replay (`declarar_topicos_kafka --resetar-offsets`).
KAFKA_GRUPO_CONSUMIDORES = os.environ.get("KAFKA_GRUPO_CONSUMIDORES", "synapseshop-pedidos")

# Grupo do replayer, SEPARADO do principal de propósito: se compartilhassem o
# grupo, o replayer disputaria partições com o worker e as mensagens de retry
# parariam de ser devolvidas.
KAFKA_GRUPO_REPLAY = os.environ.get("KAFKA_GRUPO_REPLAY", "synapseshop-replay")

# Onde começar quando o grupo ainda não tem offset: `earliest` para o teste de
# replay ler o histórico já publicado. Em produção o padrão seguro é `latest`
# (não reprocessar o passado); ver a nota no README.
KAFKA_AUTO_OFFSET_RESET = os.environ.get("KAFKA_AUTO_OFFSET_RESET", "earliest")

# Passo do laço do replayer (s): é a granularidade com que um degrau vencido é
# percebido. 1 s sobre degraus de 5/15/45 s erra o backoff em no máximo 1 s,
# muito abaixo da folga da retenção.
KAFKA_REPLAYER_PASSO_S = float(os.environ.get("KAFKA_REPLAYER_PASSO_S", "1.0"))

# =====================================================================
# Aula 11 — segundo fluxo de eventos: pagamento ➔ notificação
# =====================================================================
# A Aula 9/10 fechou o fluxo do pedido. A Aula 11 acrescenta o segundo fluxo, e
# ele é um TÓPICO À PARTE, não mais um tipo de evento dentro de
# `pedidos.criados`. Três razões:
#
# 1. **Grupo e offset próprios.** Cada fluxo é consumido por um worker
#    diferente (`worker-kafka` e `worker-pagamentos`). Se dividissem o tópico,
#    as duas task queues estariam no mesmo grupo e uma competiria com a outra
#    por partições — slower, e impossível escalar um sem o outro.
# 2. **DLQ própria.** Um `PagamentoRegistrado` malformado não pode arrastar
#    para a `pedidos.criados.dlq` uma cópia de um `PedidoCriado` que talvez
#    estivesse sadia: a DLQ precisa dizer *qual* fluxo parou.
# 3. **Escalabilidade independente.** São 3 partições por fluxo, então dá para
#    subir 3 workers de pagamento sem tocar nos 3 de pedidos.
#
# A política de reentrega é COMPARTILHADA (`PEDIDO_MAX_REENTREGAS` e
# `PEDIDO_BACKOFF_SEGUNDOS`): os dois fluxos precisam do mesmo comportamento, e
# duas escadas configuráveis separadamente seriam duas chances de errar. O que
# muda entre eles é o nome — e o nome é derivado do tópico base, então
# `pagamentos.registrados.retry.1` nasce sem nenhuma constante nova.

KAFKA_TOPICO_PAGAMENTOS = os.environ.get(
    "KAFKA_TOPICO_PAGAMENTOS", "pagamentos.registrados"
)
KAFKA_TOPICO_PAGAMENTOS_DLQ = os.environ.get(
    "KAFKA_TOPICO_PAGAMENTOS_DLQ", "pagamentos.registrados.dlq"
)
KAFKA_GRUPO_PAGAMENTOS = os.environ.get(
    "KAFKA_GRUPO_PAGAMENTOS", "synapseshop-pagamentos"
)
KAFKA_GRUPO_PAGAMENTOS_REPLAY = os.environ.get(
    "KAFKA_GRUPO_PAGAMENTOS_REPLAY", "synapseshop-pagamentos-replay"
)
KAFKA_PARTICOES_PAGAMENTOS = int(
    os.environ.get("KAFKA_PARTICOES_PAGAMENTOS", str(KAFKA_PARTICOES))
)

# Interruptor da falha forçada no fluxo de pagamento, e é **a mesma forma** do
# `PEDIDO_PERMITIR_SIMULACAO_FALHA`: quem o consulta é a **API**, no
# `_simular_falha_pagamento` da view, para decidir se aceita o header
# `X-Simular-Falha` e grava `simular_falha=true` no pagamento. O worker NÃO
# consulta nenhuma das duas flags - ele honra a marcação gravada no banco, e
# ponto. Assim os dois fluxos se comportam igual, e não existe um estado
# intermediário em que "quem liga a sabotagem esqueceu uma metade".
#
# A flag é separada da de pedidos (`PEDIDO_PERMITIR_SIMULACAO_FALHA`) porque a
# falha injetada manda a mensagem para a DLQ **do fluxo de pagamento**, e ter as
# duas sabotagens no mesmo interruptor tornaria "qual fluxo parou?" mais difícil
# de responder do que precisava.
#
# Default `False` (o Compose liga) porque é o interruptor de uma pathogenicidade:
# com ele ligado, qualquer cliente pode marcar o próprio pagamento para falhar
# até a DLQ. Fora de desenvolvimento, o header precisa ser ignorado.
PAGAMENTO_PERMITIR_SIMULACAO_FALHA = _env_flag(
    "PAGAMENTO_PERMITIR_SIMULACAO_FALHA", "False"
)

# =====================================================================
# Aula 8 — Logging estruturado (JSON) do cache
# =====================================================================
# Um logger dedicado ("core.cache") emite UMA LINHA JSON por evento de
# cache (hit/miss/invalidação/erro). O formato é o mesmo em toda a
# estrutura, o que permite filtrar no `docker compose logs` por
# resultado/namespace e alimentar o dashboard da Aula 19.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "json": {
            "()": "core.logging_utils.JsonLogFormatter",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "json",
        },
    },
"loggers": {
        "core.cache": {
            "handlers": ["console"],
            "level": os.environ.get("CACHE_LOG_LEVEL", "INFO"),
            # False para o evento não ser reemitido pelos loggers raiz.
            "propagate": False,
        },
        # Aula 9: um logger por processo de mensageria. "core.messaging" é
        # usado pelo produtor (dentro do processo da API) e pelo consumidor
        # (dentro do processo do worker) — o `docker compose logs -f worker`
        # mostra as linhas do worker, o da API mostra as do produtor.
        "core.messaging": {
            "handlers": ["console"],
            "level": os.environ.get("MESSAGING_LOG_LEVEL", "INFO"),
            "propagate": False,
        },
    },
}
