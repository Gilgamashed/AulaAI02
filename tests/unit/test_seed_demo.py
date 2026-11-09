"""Testes da massa de demonstração da Aula 25."""

from __future__ import annotations

import re
from datetime import timedelta
from io import StringIO

import httpx
import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils import timezone

from core.management.commands.seed_demo import _quantidade_inventario
from core.models import Category, Item, Notificacao, Pagamento, Pedido

pytestmark = pytest.mark.integration


@pytest.mark.django_db
def test_seed_demo_cria_massa_minima_e_e_idempotente():
    call_command("seed_auth", verbosity=0)
    call_command("seed_demo", silent=True)

    assert Category.objects.count() == 4
    assert Item.objects.count() == 12
    assert Pedido.objects.count() == 20
    assert Pagamento.objects.count() == 14
    assert Notificacao.objects.count() == 14

    assert Pedido.objects.filter(usuario__username="demo_user").count() == 2
    assert Pedido.objects.filter(usuario__username="demo_admin").count() == 18
    assert Pagamento.objects.filter(aprovado=True).count() == 12
    assert Pagamento.objects.filter(aprovado=False).count() == 2

    pedido = Pedido.objects.order_by("id").first()
    data_original = pedido.created_at

    call_command("seed_demo", silent=True)

    assert Category.objects.count() == 4
    assert Item.objects.count() == 12
    assert Pedido.objects.count() == 20
    assert Pagamento.objects.count() == 14
    assert Notificacao.objects.count() == 14
    pedido.refresh_from_db()
    assert pedido.created_at == data_original


@pytest.mark.django_db
def test_seed_demo_exige_seed_auth():
    with pytest.raises(CommandError, match="seed_auth"):
        call_command("seed_demo", silent=True)

    assert Pedido.objects.count() == 0


@pytest.mark.django_db
def test_seed_demo_silent_nao_imprime_resumo():
    call_command("seed_auth", verbosity=0)
    saida = StringIO()

    call_command("seed_demo", silent=True, stdout=saida)

    assert saida.getvalue() == ""


@pytest.mark.django_db
def test_seed_demo_cria_skus_validos_e_produtos_ativos():
    call_command("seed_auth", verbosity=0)
    call_command("seed_demo", silent=True)

    padrao = re.compile(r"[A-Z]{2,4}-[A-Z0-9-]+")
    for produto in Item.objects.all():
        assert padrao.fullmatch(produto.sku), produto.sku
        assert produto.is_active
        assert produto.specifications
        assert produto.price > 0


@pytest.mark.django_db
def test_seed_demo_distribui_pedidos_nos_ultimos_30_dias():
    call_command("seed_auth", verbosity=0)
    call_command("seed_demo", silent=True)

    agora = timezone.now()
    pedidos = list(Pedido.objects.all())
    assert all(agora - timedelta(days=31) <= pedido.created_at <= agora for pedido in pedidos)
    dias = {pedido.created_at.date() for pedido in pedidos}
    assert len(dias) >= 15
    assert {pedido.status for pedido in pedidos} == {
        Pedido.PROCESSADO,
        Pedido.PENDENTE,
        Pedido.FALHA,
    }


@pytest.mark.django_db
def test_seed_demo_cria_notificacao_para_cada_pagamento():
    call_command("seed_auth", verbosity=0)
    call_command("seed_demo", silent=True)

    pagamentos = Pagamento.objects.prefetch_related("notificacao")
    for pagamento in pagamentos:
        assert pagamento.notificado_em is not None
        notificacao = pagamento.notificacao
        assert notificacao.pedido_id == pagamento.pedido_id
        assert notificacao.titulo
        assert notificacao.mensagem
        assert notificacao.enviada_em is not None


@pytest.mark.django_db
def test_seed_demo_nao_apaga_dados_existentes():
    call_command("seed_auth", verbosity=0)
    extra = Category.objects.create(name="Categoria Personalizada", slug="personalizada")

    call_command("seed_demo", silent=True)

    assert Category.objects.filter(pk=extra.pk).exists()
    assert Category.objects.count() == 5


def test_quantidade_inventario_fica_entre_10_e_30_e_e_estavel():
    for sku in ("SMT-IP15-128", "NBT-DLL-I5", "AUD-SNY-WH1000"):
        quantidade = _quantidade_inventario(sku)
        assert 10 <= quantidade <= 30
        assert _quantidade_inventario(sku) == quantidade


@pytest.mark.django_db
def test_seed_demo_com_inventario_popula_todos_os_produtos(monkeypatch):
    chamadas: list[tuple[str, str, dict]] = []

    def fake_chamar(metodo, caminho, payload=None):
        chamadas.append((metodo, caminho, payload))
        return (201, {"status": "ok", "data": {}})

    monkeypatch.setattr(
        "core.management.commands.seed_demo.chamar_inventario", fake_chamar
    )
    call_command("seed_auth", verbosity=0)
    saida = StringIO()

    call_command(
        "seed_demo",
        silent=True,
        com_inventario=True,
        stdout=saida,
    )

    assert saida.getvalue() == ""
    skus = set(Item.objects.filter(is_active=True).values_list("sku", flat=True))
    assert len(chamadas) == len(skus)
    assert {payload["sku"] for _, _, payload in chamadas} == skus
    for metodo, caminho, payload in chamadas:
        assert metodo == "POST"
        assert caminho == "/api/v1/inventory"
        assert 10 <= payload["quantity"] <= 30
        assert payload["reserved"] == 0
        assert payload["reorder_level"] == 5


@pytest.mark.django_db
def test_seed_demo_com_inventario_atualiza_sku_existente(monkeypatch):
    chamadas: list[tuple[str, str, dict]] = []

    def fake_chamar(metodo, caminho, payload=None):
        chamadas.append((metodo, caminho, payload))
        if metodo == "POST":
            return (409, {"status": "error", "message": "SKU já cadastrado"})
        return (200, {"status": "ok", "data": {}})

    monkeypatch.setattr(
        "core.management.commands.seed_demo.chamar_inventario", fake_chamar
    )
    call_command("seed_auth", verbosity=0)

    call_command("seed_demo", silent=True, com_inventario=True)

    posts = [chamada for chamada in chamadas if chamada[0] == "POST"]
    patches = [chamada for chamada in chamadas if chamada[0] == "PATCH"]
    assert len(posts) == len(patches) == Item.objects.filter(is_active=True).count()
    assert all(caminho.startswith("/api/v1/inventory/") for _, caminho, _ in patches)
    assert all("sku" not in payload for _, _, payload in patches)


@pytest.mark.django_db
def test_seed_demo_sem_flag_nao_chama_inventario(monkeypatch):
    def fake_chamar(*_args, **_kwargs):
        raise AssertionError("o inventário não deveria ser chamado sem a flag")

    monkeypatch.setattr(
        "core.management.commands.seed_demo.chamar_inventario", fake_chamar
    )
    call_command("seed_auth", verbosity=0)

    call_command("seed_demo", silent=True)

    assert Item.objects.count() == 12


@pytest.mark.django_db
def test_seed_demo_com_inventario_falha_quando_servico_esta_fora(monkeypatch):
    def fake_chamar(*_args, **_kwargs):
        raise httpx.ConnectError("inventory fora")

    monkeypatch.setattr(
        "core.management.commands.seed_demo.chamar_inventario", fake_chamar
    )
    call_command("seed_auth", verbosity=0)

    with pytest.raises(CommandError, match="Inventário indisponível"):
        call_command("seed_demo", silent=True, com_inventario=True)


@pytest.mark.django_db
def test_seed_demo_com_inventario_falha_por_timeout(monkeypatch):
    def fake_chamar(*_args, **_kwargs):
        raise httpx.TimeoutException("timeout")

    monkeypatch.setattr(
        "core.management.commands.seed_demo.chamar_inventario", fake_chamar
    )
    call_command("seed_auth", verbosity=0)

    with pytest.raises(CommandError, match="Tempo esgotado"):
        call_command("seed_demo", silent=True, com_inventario=True)
