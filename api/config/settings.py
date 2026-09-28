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
}

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
            # False para o evento não ser reemitido pelos loggers raíz.
            "propagate": False,
        },
    },
}
