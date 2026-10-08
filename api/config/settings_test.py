"""Settings da suíte de testes (Aula 12).

Por que um módulo de settings separado, e não `override_settings` espalhado
por cada arquivo de teste?

Porque os testes precisam ser **herméticos**: nenhuma execução pode tocar
Redis, Kafka ou RabbitMQ de verdade. Se um teste de integração publicasse num
broker real, o resultado dependeria da ordem de execução e da saúde do
contêiner — exatamente os testes intermitentes que a spec manda eliminar.
Configurar o isolamento num único lugar torna a garantia estrutural: todo
teste deste repositório já nasce sem I/O externo.

O que este módulo muda em relação a `config.settings`:

1. **Caches em memória.** `default` e `dedupe` apontam para o Redis real nos
   settings de produção (dbs diferentes por decisão da Aula 9). Em teste
   viram `LocMemCache`: o comportamento de cache-aside, TTL e janela de
   dedupe continua sendo exercitado, sem rede e sem estado compartilhado
   entre execuções.
2. **Throttling com folga.** `DEFAULT_THROTTLE_CLASSES` está sempre ativo
   (anon 20/min, user 100/min). Uma suíte com dezenas de requisições
   estouraria a cota e o teste falharia com 429 por motivo que não tem nada a
   ver com o que ele testa. Aqui as taxas sobem; o throttling em si é
   verificado de propósito em `tests/integration/test_auth_throttling.py`,
   que sobrepõe as taxas de volta para baixo.
3. **Hash de senha barato.** PBKDF2 é lento por desenho (é o que torna a
   senha segura contra brute force) e a suíte cria muitos usuários. `MD5`
   faz o mesmo trabalho de autenticar com uma fração do custo. É uma troca
   segura **porque test settings nunca servem tráfego real**.
4. **DEBUG desligado.** `DEBUG=True` devolve página de erro HTML em vez de
   JSON, o que mascara o formato de resposta que os testes de integração
   esperam.
"""

from datetime import timedelta

from .settings import *  # noqa: F403 — herda tudo o que não é isolado abaixo

# =====================================================================
# 1) Caches: nada de Redis na suíte
# =====================================================================
# Os três aliases declarados em `config.settings` são replicados aqui como
# LocMemCache. O alias "throttle" já era LocMem em produção (por decisão da
# Aula 8: o throttling não pode depender da disponibilidade do Redis), então
# ele muda só de rótulo.
#
# A suíte quer exercitar a montagem real de chaves, não um caminho paralelo
# que só o teste conhece, por isso as configurações abaixo são as mesmas de
# produção (ver `config.settings`).
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "synapseshop-test-default",
        # Mesmos prefixo e TTL da produção: o teste deve ver as chaves reais
        # ("synapseshop:item:2:detalhe"), não um esquema paralelo que só a
        # suíte conhece.
        "KEY_PREFIX": "synapseshop",
        "TIMEOUT": CACHE_TTL_LIST,  # noqa: F405
    },
    "throttle": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "synapseshop-test-throttle",
    },
    "dedupe": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "synapseshop-test-dedupe",
        "KEY_PREFIX": "synapseshop",
        "TIMEOUT": DEDUPE_TTL_SEGUNDOS,  # noqa: F405
    },
}

# =====================================================================
# 2) Throttling: taxa alta, porque o 429 é testado à parte
# =====================================================================
# A classe de throttle em si continua a mesma (core.throttling.*), que é o
# que importa: o código de produção é o exercitado.
REST_FRAMEWORK = {  # noqa: F405 — sobrescreve o dicionário herdado
    **REST_FRAMEWORK,  # noqa: F405
    "DEFAULT_THROTTLE_RATES": {
        "anon": "1000/min",
        "user": "1000/min",
        "login": "1000/min",
    },
}

# =====================================================================
# 3) Senha barata e DEBUG desligado
# =====================================================================
PASSWORD_HASHERS = [
    # primeiro da lista = é o que o Django usa
    "django.contrib.auth.hashers.MD5PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
]

DEBUG = False

# A chave de assinatura do JWT precisa existir mesmo fora do `.env`:
# sem `JWT_SIGNING_KEY`, os settings caem no `SECRET_KEY` — que já tem
# fallback de desenvolvimento, mas fixar explicitamente torna a suíte
# independente do ambiente de quem a executa.
SECRET_KEY = "chave-de-teste-nao-usar-em-producao"
JWT_SIGNING_KEY = "chave-de-assinatura-de-teste-nao-usar-em-producao"
SIMPLE_JWT = {  # noqa: F405
    **SIMPLE_JWT,  # noqa: F405
    # Token curto e determinístico: o teste que expira token não precisa
    # esperar, e o freeze do relógio torna a expiração previsível.
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=5),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=1),
}

# =====================================================================
# 4) Mensageria: nunca sair para o broker
# =====================================================================
# `MENSAGERIA_BROKER` é lido em tempo de import por `core.messaging.broker`,
# então precisa estar definido ANTES do primeiro import da aplicação — por
# isso está aqui, e não num fixture. Manter "kafka" (o padrão) em vez de um
# valor inventado faz a suíte exercitar o mesmo caminho de código da
# produção; quem impede a conexão é o mock `broker_capturado` do conftest.
MENSAGERIA_BROKER = "kafka"

# O cache de dedupe é LocMem acima, mas o TTL é o mesmo da produção para que
# a janela de idempotência testada seja a janela real.
DEDUPE_TTL_SEGUNDOS = 86400

# =====================================================================
# 5) Banco de teste efêmero
# =====================================================================
# Não há nada a sobrescrever: o pytest-django já cria e destrói um banco
# temporário por execução (prefixo `test_`) a partir do `DATABASES` herdado,
# e o `settings_test` só aponta `DATABASE_URL` para o `db` do compose.
#
# O que NÃO acontece, e é importante saber: o Django não cria a tabela
# `inventory_items`, que pertence ao Alembic do microsserviço. Por isso
# nenhum teste de integração do Django toca essa tabela, e os testes HTTP do
# inventory rodam com repositório falso (`tests/conftest.py`), sem banco.
# Nenhum teste deste repositório depende de o Alembic ter rodado.