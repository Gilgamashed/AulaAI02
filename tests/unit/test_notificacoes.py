"""Testes unitários da composição do texto da notificação (Aula 12).

`notificacoes.py` é a fronteira de apresentação: é a única parte do fluxo de
pagamento que o cliente final lê em português. Erro aqui não derruba nada — o
pagamento está correto no banco e na notificação persistida, e ainda assim o
usuário lê "R$ 150,5" sem as duas casas ou "None" no lugar do método.

A regra de domínio que os testes travam: **a notificação é derivada só de
campos do evento**. É isso que permite a reentrega gerar duplicata sem
divergir de conteúdo — e o teste do `mensagem` determinístico existe para
documentar essa garantia.
"""

from decimal import Decimal

import pytest

from core.messaging.contracts import PagamentoRegistrado
from core.notificacoes import ROTULOS_METODO, titulo_e_mensagem

pytestmark = pytest.mark.unit


def _evento(**kwargs) -> PagamentoRegistrado:
    """`PagamentoRegistrado` válido; sobrescreve o que o teste precisar."""
    base = {
        "evento": "PagamentoRegistrado",
        "versao": 1,
        "evento_id": "evt-1",
        "idempotency_key": "chave-1",
        "origem": "api",
        "ocorreu_em": "2026-03-01T12:00:00+00:00",
        "publicado_em_ms": 1772366400000,
        "pagamento_id": 9,
        "pedido_id": 42,
        "usuario_id": 7,
        "status": "aprovado",
        "metodo": "pix",
        "valor": Decimal("150.50"),
        "aprovado": True,
        "motivo_recusa": "",
        "canal_notificacao": "email",
    }
    base.update(kwargs)
    return PagamentoRegistrado(**base)


# =====================================================================
# Aprovado
# =====================================================================
def test_aprovado_titulo_e_mensagem():
    titulo, mensagem = titulo_e_mensagem(_evento())

    assert titulo == "Pagamento aprovado"
    assert mensagem == "Seu pagamento de R$ 150.50 via PIX foi aprovado."


# =====================================================================
# Recusado: com motivo e sem motivo
# =====================================================================
def test_recusado_inclui_o_motivo():
    """A recusa precisa dizer por quê — é o que o cliente precisa para agir."""
    titulo, mensagem = titulo_e_mensagem(
        _evento(
            aprovado=False,
            status="recusado",
            motivo_recusa="saldo insuficiente",
        )
    )

    assert titulo == "Pagamento recusado"
    assert mensagem.endswith("foi recusado: saldo insuficiente")


def test_recusado_sem_motivo_encerra_com_ponto():
    """Sem motivo, a frase fecha com ponto em vez de dois-pontos soltos.

    Doispontos soltos produziriam "foi recusado: ." — o tipo de detalhe que só
    aparece na tela do cliente em produção.
    """
    _, mensagem = titulo_e_mensagem(_evento(aprovado=False, status="recusado"))

    assert mensagem.endswith("foi recusado.")
    assert "recusado:" not in mensagem


# =====================================================================
# Métodos de pagamento
# =====================================================================
@pytest.mark.parametrize(
    ("metodo", "rotulo_esperado"),
    [
        pytest.param("cartao_credito", "cartão de crédito", id="cartao"),
        pytest.param("pix", "PIX", id="pix"),
        pytest.param("boleto", "boleto", id="boleto"),
        # Método desconhecido passa adiante: um método novo no contrato não pode
        # quebrar o texto da notificação.
        pytest.param("cripto", "cripto", id="metodo_desconhecido_passa_adiante"),
    ],
)
def test_rotulo_do_metodo(metodo, rotulo_esperado):
    _, mensagem = titulo_e_mensagem(_evento(metodo=metodo))

    assert f"via {rotulo_esperado}" in mensagem


def test_rotulos_declarados_cobrem_o_mapa_usado():
    """Trava o mapa de rótulos contra a lista que a suíte exercita.

    Sem este teste, remover um método de `ROTULOS_METODO` derrubaria o
    `parametrize` acima — mas a suíte não perceberia que a tabela de rótulos
    documentada no código ficou incompleta.
    """
    exercitados = {"cartao_credito", "pix", "boleto"}

    assert exercitados <= set(ROTULOS_METODO)


# =====================================================================
# Formatação do valor
# =====================================================================
@pytest.mark.parametrize(
    ("valor", "trecho_esperado"),
    [
        pytest.param(Decimal("0.00"), "R$ 0.00", id="zero"),
        pytest.param(Decimal("150.5"), "R$ 150.50", id="uma_casa_vira_duas"),
        pytest.param(Decimal("150.567"), "R$ 150.57", id="arredonda_para_cima"),
        pytest.param(Decimal("1000.00"), "R$ 1000.00", id="mil"),
    ],
)
def test_valor_sempre_com_duas_casas(valor, trecho_esperado):
    """`:.2f` é o que garante "150.50" em vez de "150.5"."""
    _, mensagem = titulo_e_mensagem(_evento(valor=valor))

    assert trecho_esperado in mensagem


# =====================================================================
# Determinismo
# =====================================================================
def test_mesmo_evento_gera_mesmo_texto():
    """Dois processamentos do mesmo evento produzem texto idêntico.

    É a garantia que permite a reentrega gerar duplicata de notificação sem
    divergir de conteúdo: nada aqui depende de relógio, de contador ou de
    ordem de execução.
    """
    evento = _evento(aprovado=False, status="recusado", motivo_recusa="cartão recusado")

    assert titulo_e_mensagem(evento) == titulo_e_mensagem(evento)