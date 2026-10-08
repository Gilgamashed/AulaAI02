"""Integração: ciclo de vida de recursos do catálogo via HTTP + reflexo no banco.

É o par que a spec da Aula 12 pede explicitamente no DoD 4: um teste que
execute o endpoint e verifique o efeito na base de dados. O cache-aside e o
locmem continuam ativos (vindos do settings_test) — o que este arquivo prova
é o fluxo completo: criar grava, ler devolve e o banco confirma.

Escolha dos recursos: `categorias` e `itens` são os dois CRUDs completos do
catálogo. Verificamos o POST (criação), o GET (leitura — reforçando que o
retrieve de detalhe funciona), o detalhe pesado `/items/{id}/detalhes/`
(exercita o `ItemDetalheSerializer`, fonte das 4 consultas da Aula 8) e a
listagem pública, que é a leitura que um anônimo faz do catálogo.
"""

import pytest
from core.models import Category, Item

pytestmark = pytest.mark.integration


def test_ciclo_de_vida_da_categoria(client_admin, db):
    resposta = client_admin.post(
        "/api/v1/categories/",
        {"name": "Integração Aula 12", "description": "criada pela suíte"},
        format="json",
    )

    assert resposta.status_code == 201, resposta.content
    categoria_id = resposta.data["id"]

    detalhe = client_admin.get(f"/api/v1/categories/{categoria_id}/")
    assert detalhe.status_code == 200, detalhe.content
    assert detalhe.data["name"] == "Integração Aula 12"

    assert Category.objects.filter(
        pk=categoria_id, name="Integração Aula 12"
    ).exists()


def test_ciclo_de_vida_do_item(client_admin, categoria, db):
    resposta = client_admin.post(
        "/api/v1/items/",
        {
            "name": "Monitor Aula 12",
            "brand": "MarcaTeste",
            "model": "M1201",
            "sku": "AUL-12-MON1",
            "description": "criado pela suíte",
            "price": "1299.90",
            "warranty_months": 24,
            "category": categoria.pk,
        },
        format="json",
    )

    assert resposta.status_code == 201, resposta.content
    item_id = resposta.data["id"]

    detalhe = client_admin.get(f"/api/v1/items/{item_id}/")
    assert detalhe.status_code == 200, detalhe.content
    assert detalhe.data["sku"] == "AUL-12-MON1"
    assert detalhe.data["category_name"] == categoria.name

    assert Item.objects.filter(pk=item_id, sku="AUL-12-MON1").exists()


def test_detalhe_pesado_do_item(client_admin, item, db):
    resposta = client_admin.get(f"/api/v1/items/{item.pk}/detalhes/")

    assert resposta.status_code == 200, resposta.content
    assert resposta.data["sku"] == item.sku
    assert resposta.data["categoria"]["id"] == item.category_id
    assert "estatisticas_categoria" in resposta.data
    assert "itens_mais_caros" in resposta.data
    # `get_itens_recentes` costumava estar fora da classe (indentação errada) —
    # este assert é a regressão que garante que o campo resolve de verdade.
    assert "itens_recentes" in resposta.data


def test_listagem_publica_do_catalogo(api_client, categoria, item, db):
    resposta = api_client.get("/api/v1/items/")

    assert resposta.status_code == 200, resposta.content
    skus = [item_corpo["sku"] for item_corpo in resposta.data["results"]]
    assert item.sku in skus