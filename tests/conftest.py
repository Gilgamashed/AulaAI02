"""Fixtures e mocks globais da suíte (Aula 12).

Este arquivo é o ponto único de isolamento. A spec pede fixtures para a
aplicação de teste, cliente HTTP, banco efêmero e relógio fixo, além de
mocks para as dependências externas; aqui todas moram juntas porque é a
possibilidade de um teste quebrar por vazamento de estado que decide se a
suíte é confiável.

Três decisões estruturam o resto:

**1. Nenhum teste toca serviço externo.** Redis, Kafka e RabbitMQ são
substituídos por duplos ou por cache em memória (ver
`api/config/settings_test.py`). Um teste que dependesse da saúde do broker
seria instável por construção: passaria numa máquina e falharia na outra.

**2. Os mocks de broker são `autouse`.** Não é conveniência, é garantia: um
teste novo que publique um pedido não pode, por esquecimento, enviar um
evento de verdade. O duplo está no lugar antes do corpo do teste rodar.

**3. Estado global é zerado entre testes.** O projeto tem contadores de
métricas em memória (`cache.cache_metrics`, `messaging.metricas`) e cache de
throttling. Sem `reset()`, o número de métricas de um teste vaza para o
asserção do seguinte — que é a receita clássica de teste intermitente.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.cache import caches
from freezegun import freeze_time

# =====================================================================
# Relógio fixo
# =====================================================================
# A spec pede explicitamente um "relógio fixo". Duas razões, e a segunda é
# a que costuma doer:
#
#  - timestamp de contrato (`_envelope_comum` em contracts.py) entra no
#    dicionário serializado; um teste que compara o payload inteiro passaria
#    ou falharia conforme o minuto em que rodou;
#  - janela de dedupe e TTL são calculados a partir de `time.time()`, então
#    um teste de expiração precisa de um tempo que não anda.
#
# `tick=False` é o detalhe que importa: sem ele o relógio congelado avança
# 1 segundo a cada chamada, o que torna um TTL de 5s expirar no meio do
# próprio teste.
INSTANTE_FIXO = datetime(2026, 3, 1, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def relogio_fixo():
    """Congela o tempo em um instante fixo (UTC).

    Uso: `with relogio_fixo():` no corpo do teste. É o formato explícito em
    vez de fixture `autouse` porque congelar o relógio globalmente quebraria
    a expiração de token JWT e a própria resolução do Django.
    """
    return freeze_time(INSTANTE_FIXO, tick=False)


# =====================================================================
# Isolamento de estado (autouse)
# =====================================================================
@pytest.fixture(autouse=True)
def _estado_limpo():
    """Zera cache e contadores de métricas antes e depois de cada teste.

    `autouse` porque o vazamento é invisível na leitura do teste: quem
    escreve `assert metrics.total == 1` não tem como saber que o 1 é
    herança do teste anterior. Automatizar é a única forma de não depender
    da disciplina de quem escreve o teste.
    """
    from core.cache_metrics import cache_metrics
    from core.llm.metricas import llm_metrics
    from core.messaging.metricas import mensageria_metrics

    def _zerar():
        # Os três aliases existem para permitir o reset por cache — `default`
        # e `dedupe` guardam janelas e chaves, `throttle` guarda a cota de
        # login. Um 429 disparado por um teste vazaria para o seguinte.
        for alias in ("default", "throttle", "dedupe"):
            caches[alias].clear()
        cache_metrics.reset()
        mensageria_metrics.reset()
        llm_metrics.reset()

    _zerar()
    yield
    _zerar()


# =====================================================================
# Mocks de broker (autouse)
# =====================================================================
@pytest.fixture(autouse=True)
def broker_capturado(monkeypatch):
    """Substitui a publicação de eventos por um duplo em memória.

    Substitui `core.messaging.broker.publicar_pedido_criado` e
    `publicar_pagamento_registrado`. Ponto importante: o patch é feito no
    módulo `broker`, e não no `kafka_produtor`. As views importam o módulo
    (`from core.messaging import broker as mensageria`) e chamam
    `mensageria.publicar_pedido_criado(...)` — um patch no produtor deixaria
    a view chamar o broker de verdade na primeira vez.

    O duplo devolve um recibo no mesmo formato do real, porque as views
    copiam esse dicionário para a resposta HTTP (`corpo["evento"] =
    publicacao`) e a suíte de integração faz asserção sobre ele.

    Para exercitar o caminho de falha (503 quando o broker está fora),
    o teste injeta a exceção:

        broker_capturado.falhar_com = PublicacaoFalhou("broker fora")
    """
    from core.messaging import broker as mensageria

    #: Lista de eventos publicados no teste, na ordem das chamadas.
    publicados: list[dict] = []

    class _Publicacao:
        """Duplo de publicação. `falhar_com` vira uma exceção na próxima chamada."""

        def __init__(self) -> None:
            self.falhar_com: Exception | None = None
            self.quantidade_publicada = 0

        def _registrar(self, fluxo: str, evento_id: str) -> dict:
            if self.falhar_com is not None:
                raise self.falhar_com
            self.quantidade_publicada += 1
            return {
                "evento_id": evento_id,
                "fluxo": fluxo,
                "topico": f"{fluxo}.criados",
                "publicado": True,
                "duplicado": False,
            }

        def pedido_criado(self, pedido, chave):
            evento_id = f"evt-pedido-{pedido.pk}"
            publicacao = self._registrar("pedidos", evento_id)
            publicados.append({"fluxo": "pedidos", "pedido_id": pedido.pk, "chave": chave})
            return publicacao

        def pagamento_registrado(self, pagamento):
            evento_id = f"evt-pagamento-{pagamento.pk}"
            publicacao = self._registrar("pagamentos", evento_id)
            publicados.append({"fluxo": "pagamentos", "pagamento_id": pagamento.pk})
            return publicacao

    duplo = _Publicacao()
    monkeypatch.setattr(mensageria, "publicar_pedido_criado", duplo.pedido_criado)
    monkeypatch.setattr(mensageria, "publicar_pagamento_registrado", duplo.pagamento_registrado)

    duplo.publicados = publicados
    yield duplo


# =====================================================================
# Usuários e autenticação
# =====================================================================
# Os papéis são `Group` do django.contrib.auth, não um model próprio — a
# decisão vem da Aula 6 (reutilizar o auth do Django em vez de customizar
# AUTH_USER_MODEL). Os testes precisam recriar esse mapeamento para que
# `IsAdminRole` funcione.
@pytest.fixture
def grupo_admin(db):
    return Group.objects.get_or_create(name="admin")[0]


@pytest.fixture
def grupo_user(db):
    return Group.objects.get_or_create(name="user")[0]


@pytest.fixture
def usuario(db, grupo_user):
    """Usuário comum, papel `user`."""
    User = get_user_model()
    user = User.objects.create_user(username="teste_user", password="Teste@123456")
    user.groups.add(grupo_user)
    return user


@pytest.fixture
def usuario_admin(db, grupo_admin):
    """Usuário administrador, papel `admin`."""
    User = get_user_model()
    admin = User.objects.create_user(
        username="teste_admin", password="Teste@123456", is_staff=True
    )
    admin.groups.add(grupo_admin)
    return admin


@pytest.fixture
def api_client():
    """Cliente DRF sem autenticação."""
    from rest_framework.test import APIClient

    return APIClient()


@pytest.fixture
def client_autenticado(api_client, usuario):
    """Cliente DRF autenticado como usuário comum."""
    api_client.force_authenticate(usuario)
    return api_client


@pytest.fixture
def client_admin(api_client, usuario_admin):
    """Cliente DRF autenticado como administrador."""
    api_client.force_authenticate(usuario_admin)
    return api_client


# =====================================================================
# Inventory (microsserviço FastAPI) — repositório falso
# =====================================================================
# O settings_test promete que "os testes HTTP do inventory rodam com
# repositório falso, sem banco": o FastAPI nunca cria sessão do SQLAlchemy na
# suíte, porque a dependência `get_inventory_service` injetada pelas rotas é
# substituída por um serviço sobre o duplo em memória abaixo.
class _SessaoFake:
    """Sessão falsa com a superfície que o serviço usa: commit/rollback.

    O `InventoryService` chama `self._repository.session.commit()` em toda
    escrita e `rollback()` se o commit falhar; este duplo conta as chamadas e
    permite injetar uma falha de commit para exercitar o caminho de rollback.
    """

    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0
        self.falhar_commit: Exception | None = None

    def commit(self) -> None:
        self.commits += 1
        if self.falhar_commit is not None:
            raise self.falhar_commit

    def rollback(self) -> None:
        self.rollbacks += 1


class InventoryRepositoryFake:
    """Duplo em memória do `InventoryRepository` (sem SQLAlchemy).

    Espelha a interface usada pelo `InventoryService`: list, get_by_sku,
    create, update e delete — e expõe `session` porque o serviço acessa
    `_repository.session.commit()` direto. O duplo preenche `id`,
    `created_at` e `updated_at` para que a validação `from_attributes` do
    schema na rota encontre os campos que a persistência real geraria.
    """

    def __init__(self) -> None:
        self._itens: dict[str, InventoryItem] = {}
        self._proximo_id = 1
        self.session = _SessaoFake()

    def list(self) -> list[InventoryItem]:
        return sorted(self._itens.values(), key=lambda item: item.id)

    def get_by_sku(self, sku: str) -> InventoryItem | None:
        return self._itens.get(sku)

    def create(self, item: InventoryItem) -> InventoryItem:
        from datetime import datetime, timezone

        item.id = self._proximo_id
        item.created_at = datetime.now(timezone.utc)
        item.updated_at = item.created_at
        self._proximo_id += 1
        self._itens[item.sku] = item
        return item

    def update(self, item: InventoryItem, updates: dict[str, object]) -> InventoryItem:
        from datetime import datetime, timezone

        for campo, valor in updates.items():
            setattr(item, campo, valor)
        item.updated_at = datetime.now(timezone.utc)
        return item

    def delete(self, item: InventoryItem) -> None:
        self._itens.pop(item.sku, None)


@pytest.fixture
def inventory_repository_fake() -> InventoryRepositoryFake:
    """Repo falso vazio — os testes de serviço inserem e asserem sobre ele."""
    return InventoryRepositoryFake()


@pytest.fixture
def inventory_service_fake(inventory_repository_fake) -> InventoryService:
    """Serviço de negócio do inventory sobre o repositório em memória."""
    from app.services.inventory import InventoryService

    return InventoryService(inventory_repository_fake)


@pytest.fixture
def inventory_client(inventory_service_fake: InventoryService):
    """TestClient do FastAPI com a dependência de serviço substituída.

    As rotas injetam `get_inventory_service` via `Depends`; substituí-la no
    `app.dependency_overrides` isola o HTTP do banco real — nenhuma sessão do
    SQLAlchemy é criada pela suíte, mesmo nos endpoints que em produção fazem
    `get_session()`.
    """
    from fastapi.testclient import TestClient

    from app.dependencies import get_inventory_service
    from app.main import app

    app.dependency_overrides[get_inventory_service] = lambda: inventory_service_fake
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


# =====================================================================
# Throttling: taxa baixa sob demanda
# =====================================================================
@pytest.fixture
def throttling_baixo(monkeypatch):
    """Baixa a taxa do scope `login` para o teste de 429 ser possível.

    O `settings_test` sobe TOdas as taxas para 1000/min de propósito (uma
    suíte com dezenas de requisições não pode estourar cota por acidente).
    Este teste específico precisa da taxa real da Aula 7 — a prova do 429 —,
    então sobrepõe só o scope `login` de volta para um valor baixo.

    Por que patchar o atributo de classe e não `override_settings`? O mixin
    `SimpleRateThrottle.THROTTLE_RATES` é capturado uma única vez, na
    definição da classe (`api_settings.DEFAULT_THROTTLE_RATES` no import);
    trocar o `REST_FRAMEWORK` no settings não rebinda o atributo da classe
    já instanciada, e a taxa lida no `parse_rate` continuaria a de 1000/min.
    """
    from core import throttling as mod_throttling

    taxas = {**mod_throttling.ThrottleMemoriaScope.THROTTLE_RATES, "login": "1/min"}
    monkeypatch.setattr(mod_throttling.ThrottleMemoriaScope, "THROTTLE_RATES", taxas)
    yield


# =====================================================================
# Fábricas de dados
# =====================================================================
@pytest.fixture
def categoria(db):
    """Categoria válida para envolver itens."""
    from core.models import Category

    return Category.objects.create(name="Eletrônicos", description="Categoria de teste")


@pytest.fixture
def item(db, categoria):
    """`Item` válido, associado à `categoria`, para os fluxos de pedido."""
    from core.models import Item

    return Item.objects.create(
        sku="TEST-001",
        name="Notebook Teste",
        description="Item criado pela suíte de testes",
        brand="MarcaTeste",
        model="ModelX",
        price=Decimal("1000.00"),
        category=categoria,
        is_active=True,
    )