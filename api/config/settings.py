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
    "core",
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
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "anon": "20/min",
        "user": "100/min",
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
    # Assinatura com chave própria (JWT_SIGNING_KEY) separada do SECRET_KEY
    # do Django. Se ausente no .env, usa o SECRET_KEY como fallback — nunca
    # um segredo hardcoded.
    "SIGNING_KEY": os.environ.get("JWT_SIGNING_KEY", SECRET_KEY),
}
