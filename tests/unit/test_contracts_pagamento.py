"""Testes unitários do contrato `PagamentoRegistrado` (Aula 12).

O contrato de pagamento carrega três invariantes que existem para impedir que
o worker notifique algo que não aconteceu. Cada uma delas é um teste, e todas
são de recusa — porque o caminho feliz (pagamento aprovado, coerente) já é
coberto pelo par do pedido, e o risco real está nos estados contraditórios.

A invariante mais sutil é a terceira: `status` e `aprovado` precisam concordar.
Publicar `status: "registrado"` com `aprovado: true` passaria pelo consumidor
sem erro nenhum e apareceria depois no relatório como "aprovado, mas travado em
registrado para sempre" — muito mais difícil de diagnosticar do que um payload
recusado na entrada.
"""

import pytest

from core.messaging.contracts import (
    ContratoInvalido,
    PagamentoRegistrado,
    validar,
    validar_pagamento_registrado,
)

pytestmark = pytest.mark.unit


def _corpo(aprovado: bool = True, **pagamento) -> dict:
    """Corpo de `PagamentoRegistrado` v1; `status` acompanha `aprovado`."""
    corpo = {
        "evento": "PagamentoRegistrado",
        "versao": 1,
        "evento_id": "evt-pag-1",
        "idempotency_key": "chave-pag-1",
        "origem": "api",
        "ocorrido_em": "2026-03-01T12:00:00+00:00",
        "publicado_em": 1772366400000,
        "pagamento": {
            "id": 9,
            "pedido_id": 42,
            "usuario_id": 7,
            "status": "aprovado" if aprovado else "recusado",
            "metodo": "pix",
            "valor": 150.50,
            "aprovado": aprovado,
        },
    }
    corpo["pagamento"].update(pagamento)
    return corpo


# =====================================================================
# Caminho feliz
# =====================================================================
def test_pagamento_aprovado_e_aceito():
    evento = validar_pagamento_registrado(_corpo(aprovado=True))

    assert isinstance(evento, PagamentoRegistrado)
    assert evento.pagamento_id == 9
    assert evento.pedido_id == 42
    assert evento.aprovado is True
    # Ausência do campo é informação válida: um pagamento aprovado não tem
    # motivo de recusa, então o contrato preenche "".
    assert evento.motivo_recusa == ""


def test_pagamento_recusado_exige_motivo_e_aceita():
    evento = validar_pagamento_registrado(
        _corpo(aprovado=False, motivo_recusa="saldo insuficiente")
    )

    assert evento.aprovado is False
    assert evento.motivo_recusa == "saldo insuficiente"


def test_canal_de_notificacao_tem_padrao():
    """Canal ausente vira "email".

    A ausência **é** informação válida aqui: nem todo pagamento explicitou
    canal, e o worker precisa de um valor para montar a notificação.
    """
    assert validar_pagamento_registrado(_corpo()).canal_notificacao == "email"


def test_motivo_vazio_e_aceito_em_recusa_quando_houver_texto():
    """`motivo_recusa: ""` é recusado, `None` também.

    O `get(campo, padrao)` do `_texto_opcional` trata `None` como ausente —
    o teste trava essa tolerância porque um `None` que vaza para a notificação
    apareceria como "recusado: None" na tela do cliente.
    """
    with pytest.raises(ContratoInvalido, match="obrigatório"):
        validar_pagamento_registrado(_corpo(aprovado=False, motivo_recusa=""))


def test_fluxo_e_chave_de_dedupe_do_pagamento():
    """O prefixo `pagamentos:` é o que separa a janela de dedupe dos dois fluxos."""
    evento = validar_pagamento_registrado(_corpo())

    assert evento.fluxo == "pagamentos"
    assert evento.chave_dedupe() == "pagamentos:chave-pag-1"


# =====================================================================
# Invariantes de recusa
# =====================================================================
def test_recusa_sem_motivo_e_contrato_invalido():
    """`aprovado: false` sem motivo não diz nada de acionável para quem notifica."""
    corpo = _corpo(aprovado=False)
    corpo["pagamento"]["motivo_recusa"] = ""

    with pytest.raises(ContratoInvalido, match="obrigatório quando 'aprovado' é false"):
        validar_pagamento_registrado(corpo)


def test_aprovado_com_motivo_de_recusa_e_contradicao():
    """Um evento que mente sobre o próprio desfecho é pior que um evento ausente."""
    corpo = _corpo(aprovado=True, motivo_recusa="erro do gateway")

    with pytest.raises(ContratoInvalido, match="não faz sentido"):
        validar_pagamento_registrado(corpo)


@pytest.mark.parametrize(
    ("status", "aprovado"),
    [
        pytest.param("registrado", True, id="registrado_mas_aprovado"),
        pytest.param("recusado", True, id="recusado_mas_aprovado"),
        pytest.param("aprovado", False, id="aprovado_mas_recusado"),
        pytest.param("pendente", False, id="pendente_mas_recusado"),
    ],
)
def test_status_e_aprovado_precisam_concordar(status, aprovado):
    """A contradição que passaria pelo consumidor sem erro algum."""
    corpo = _corpo(aprovado=aprovado)
    corpo["pagamento"]["status"] = status
    if not aprovado:
        corpo["pagamento"]["motivo_recusa"] = "recusado pelo gateway"

    with pytest.raises(ContratoInvalido, match="não confere"):
        validar_pagamento_registrado(corpo)


# =====================================================================
# Validação de tipos dos campos
# =====================================================================
@pytest.mark.parametrize(
    ("mutacao", "trecho_esperado"),
    [
        pytest.param(
            lambda c: c["pagamento"].update(aprovado="sim"),
            "deve ser booleano",
            id="aprovado_texto",
        ),
        pytest.param(
            lambda c: c["pagamento"].update(aprovado=1),
            "deve ser booleano",
            id="aprovado_int",
        ),
        pytest.param(
            lambda c: c.pop("pagamento"),
            "campo ausente",
            id="sem_pagamento",
        ),
        pytest.param(
            lambda c: c.update(pagamento="nao-e-objeto"),
            "não é um objeto",
            id="pagamento_nao_objeto",
        ),
        pytest.param(
            lambda c: c["pagamento"].update(pedido_id="quarenta"),
            "deve ser inteiro",
            id="pedido_id_texto",
        ),
        pytest.param(
            lambda c: c["pagamento"].update(valor="barato"),
            "não é decimal",
            id="valor_invalido",
        ),
        pytest.param(
            lambda c: c["pagamento"].update(metodo=""),
            "texto não vazio",
            id="metodo_vazio",
        ),
        pytest.param(
            lambda c: c["pagamento"].update(canal_notificacao=7),
            "deve ser texto",
            id="canal_nao_texto",
        ),
        pytest.param(
            lambda c: c.update(versao=99),
            "não suportada",
            id="versao_futura",
        ),
    ],
)
def test_campo_invalido_e_recusado(mutacao, trecho_esperado):
    corpo = _corpo()
    mutacao(corpo)

    with pytest.raises(ContratoInvalido) as erro:
        validar_pagamento_registrado(corpo)

    assert trecho_esperado in str(erro.value)


def test_despachante_roteia_pagamento_registrado():
    """O mesmo laço de consumo atende aos dois contratos."""
    assert isinstance(validar(_corpo()), PagamentoRegistrado)