"""Testes da massa de demonstração da Aula 25."""

from __future__ import annotations

import re
from datetime import timedelta
from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils import timezone

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
