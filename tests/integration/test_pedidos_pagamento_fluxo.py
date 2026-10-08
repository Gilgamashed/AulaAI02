"""Integração: fluxo de pedido e pagamento (Aula 9 e 11) via HTTP e banco.

O POST de pedido publica `PedidoCriado`; o POST de pagamento publica
`PagamentoRegistrado`. Com o `broker_capturado` do conftest, as publicações
vão para o duplo em memória — e a asserção é dupla: o corpo da resposta traz
o recibo (`evento`) e o banco confirma o efeito esperado.

Também é aqui que os achados de idempotência são provados:

* pedido: o re-POST (com a mesma chave canônica, ou com o mesmo header
  `Idempotency-Key`) devolve 200 com o pedido já existente, sem criar segundo
  pedido nem publicar segundo evento;
* pagamento: a segunda tentativa com outro método cai no `OneToOne` e
 * devolve 409 com o pagamento existente no corpo.

Por que `transaction=True` nos fluxos de sucesso: a view publica o evento
via `transaction.on_commit` (em `api/core/views.py`, `_publicar`). Sem
transação ativa em autocommit — o caso de produção — o callback roda na
hora, antes da resposta; mas o pytest-django envolve cada teste numa
transação e, dentro dela, o `on_commit` fica adiado até o fim do teste.
Esses testes trocam o wrapping por commits reais (`transaction=True`) para
reproduzir a semântica de produção: sem isso o POST devolveria 503 porque
a publicação ainda não aconteceu quando a resposta é montada.
"""

import pytest
from core.models import Pagamento, Pedido

pytestmark = pytest.mark.integration


def _criar_pedido(client, **extra) -> dict:
    """POST `/api/v1/pedidos/` e devolve a resposta."""
    return client.post(
        "/api/v1/pedidos/",
        {"itens": [{"sku": "TEST-001", "quantidade": 2}]},
        format="json",
        **extra,
    )


@pytest.mark.django_db(transaction=True)
def test_criar_pedido_persiste_publica_evento(
    client_autenticado, usuario, item, broker_capturado, db
):
    resposta = _criar_pedido(client_autenticado)

    assert resposta.status_code == 201, resposta.content
    corpo = resposta.data
    assert corpo["evento"]["fluxo"] == "pedidos"
    assert corpo["evento"]["topico"] == "pedidos.criados"

    pedido = Pedido.objects.get(pk=corpo["id"])
    assert pedido.usuario_id == usuario.pk
    assert pedido.status == "pendente"
    assert pedido.total == 2000
    assert pedido.itens[0]["sku"] == "TEST-001"

    assert broker_capturado.quantidade_publicada == 1
    assert broker_capturado.publicados[0]["fluxo"] == "pedidos"


@pytest.mark.django_db(transaction=True)
def test_repost_sem_header_nao_duplica_pedido_identico(
    client_autenticado, item, broker_capturado, db
):
    primeira = _criar_pedido(client_autenticado)
    assert primeira.status_code == 201, primeira.content

    # Mesmo corpo, sem header: a chave canônica (sha256 do conteúdo) é a
    # mesma, portanto o re-POST é reconhecido como repetição.
    segunda = _criar_pedido(client_autenticado)

    assert segunda.status_code == 200, segunda.content
    assert segunda.data["evento"]["duplicado"] is True
    assert Pedido.objects.count() == 1
    assert broker_capturado.quantidade_publicada == 1


@pytest.mark.django_db(transaction=True)
def test_repost_com_mesma_idempotency_key_devolve_200(
    client_autenticado, item, broker_capturado, db
):
    cabecalho = {"Idempotency-Key": "chave-pedido-teste-1"}

    primeira = _criar_pedido(client_autenticado, HTTP_IDEMPOTENCY_KEY=cabecalho["Idempotency-Key"])
    assert primeira.status_code == 201, primeira.content

    repetida = _criar_pedido(client_autenticado, HTTP_IDEMPOTENCY_KEY=cabecalho["Idempotency-Key"])

    assert repetida.status_code == 200, repetida.content
    assert repetida.data["evento"]["duplicado"] is True
    assert Pedido.objects.count() == 1
    assert broker_capturado.quantidade_publicada == 1


def test_pedido_anomino_retorna_401(api_client, item, db):
    resposta = _criar_pedido(api_client)

    assert resposta.status_code == 401


def test_pedido_com_sku_fora_do_catalogo_retorna_404(
    client_autenticado, db, broker_capturado
):
    resposta = client_autenticado.post(
        "/api/v1/pedidos/",
        {"itens": [{"sku": "ZZZ-0001", "quantidade": 1}]},
        format="json",
    )

    assert resposta.status_code == 404
    assert "SKU inexistente ou inativo" in resposta.data["detail"]


@pytest.mark.django_db(transaction=True)
def test_pagamento_aprovado_publica_evento_e_persiste(
    client_autenticado, item, broker_capturado, db
):
    pedido = _criar_pedido(client_autenticado).data

    resposta = client_autenticado.post(
        f"/api/v1/pedidos/{pedido['id']}/pagamento/",
        {"metodo": "pix", "aprovado": True, "canal": "email"},
        format="json",
    )

    assert resposta.status_code == 201, resposta.content
    corpo = resposta.data
    assert corpo["evento"]["fluxo"] == "pagamentos"
    assert corpo["evento"]["topico"] == "pagamentos.criados"

    pagamento = Pagamento.objects.get(pk=corpo["id"])
    assert pagamento.pedido_id == pedido["id"]
    assert pagamento.metodo == "pix"
    assert pagamento.aprovado is True
    assert pagamento.status == "registrado"

    assert broker_capturado.quantidade_publicada == 2  # pedido + pagamento

    leitura = client_autenticado.get(f"/api/v1/pedidos/{pedido['id']}/pagamento/")
    assert leitura.status_code == 200
    assert leitura.data["id"] == pagamento.pk


@pytest.mark.django_db(transaction=True)
def test_recusa_sem_motivo_retorna_400(
    client_autenticado, item, broker_capturado, db
):
    pedido = _criar_pedido(client_autenticado).data

    resposta = client_autenticado.post(
        f"/api/v1/pedidos/{pedido['id']}/pagamento/",
        {"metodo": "boleto", "aprovado": False},
        format="json",
    )

    assert resposta.status_code == 400
    assert "motivo_recusa" in resposta.data
    assert Pagamento.objects.count() == 0


@pytest.mark.django_db(transaction=True)
def test_pagamento_tentativa_com_outro_metodo_retorna_409(
    client_autenticado, item, broker_capturado, db
):
    pedido = _criar_pedido(client_autenticado).data

    primeiro = client_autenticado.post(
        f"/api/v1/pedidos/{pedido['id']}/pagamento/",
        {"metodo": "pix", "aprovado": True},
        format="json",
    )
    assert primeiro.status_code == 201

    segundo = client_autenticado.post(
        f"/api/v1/pedidos/{pedido['id']}/pagamento/",
        {"metodo": "boleto", "aprovado": True},
        format="json",
    )

    assert segundo.status_code == 409
    assert segundo.data["pagamento_existente"]["metodo"] == "pix"
    assert Pagamento.objects.count() == 1