"""Testes unitários do contrato `PedidoCriado` (Aula 12).

Por que `contracts.py` é o primeiro alvo da suíte:

O contrato é a fronteira entre a API e o worker, e um contrato aceito errado
não dá erro visível — o consumidor simplesmente aplica o efeito com os dados
que entendeu. Um `total` lido de um campo trocado, ou uma versão não
suportada silenciosamente aceita, só apareceria no relatório financeiro. Por
isso a validação merece teste caso a caso, e este arquivo cobre as duas
metades: o caminho feliz e cada caminho de recusa.

Todos os testes são parametrizados porque a regra é a mesma mudando o dado de
entrada — exatamente o caso que o `parametrize` expressa melhor do que N
funções quase idênticas.
"""

import pytest

from core.messaging.contracts import (
    ContratoInvalido,
    PedidoCriado,
    serializar,
    validar,
    validar_pedido_criado,
)

pytestmark = pytest.mark.unit


def _corpo_valido() -> dict:
    """Corpo mínimo válido de um `PedidoCriado` v1.

    Função (e não constante de módulo) porque os testes precisam mutar uma
    parte do corpo por vez; se fosse um dicionário único compartilhado, a
    primeira mutação contaminaria todos os testes seguintes.
    """
    return {
        "evento": "PedidoCriado",
        "versao": 1,
        "evento_id": "evt-123",
        "idempotency_key": "chave-abc",
        "origem": "api",
        "ocorrido_em": "2026-03-01T12:00:00+00:00",
        "publicado_em": 1772366400000,
        "pedido": {
            "id": 42,
            "usuario_id": 7,
            "status": "pendente",
            "total": 1999.90,
            "itens": [
                {"sku": "TEST-001", "quantidade": 2, "preco_unitario": 999.95},
            ],
        },
    }


# =====================================================================
# Caminho feliz
# =====================================================================
def test_corpo_valido_vira_evento_tipado():
    evento = validar_pedido_criado(_corpo_valido())

    assert isinstance(evento, PedidoCriado)
    assert evento.evento == "PedidoCriado"
    assert evento.versao == 1
    assert evento.pedido_id == 42
    assert evento.usuario_id == 7
    assert len(evento.itens) == 1
    assert evento.itens[0].sku == "TEST-001"
    assert evento.itens[0].quantidade == 2


def test_total_em_centavos_preserva_os_dois_ultimos_digitos():
    """O total vai para o contrato em centavos, não em reais.

    Multiplicar por 100 e quantizar é o que evita que 1999.90 chegue ao
    worker como 1999.9 (float) e que o worker some 1999.90 reais num total
    que o cliente viu como 1999 reais.
    """
    evento = validar_pedido_criado(_corpo_valido())

    assert evento.total_em_centavos == 199990


def test_chave_dedupe_prefixa_o_fluxo():
    """A chave de dedupe é namespaced pelo fluxo.

    Sem o prefixo `pedidos:`, um pedido e um pagamento com o mesmo
    `idempotency_key` colidiriam na janela de dedupe e um seria tratado como
    duplicata do outro.
    """
    evento = validar_pedido_criado(_corpo_valido())

    assert evento.chave_dedupe() == "pedidos:chave-abc"
    assert evento.fluxo == "pedidos"


def test_serializar_gera_bytes_utf8():
    """A serialização precisa preservar acentos.

    `ensure_ascii=False` + UTF-8: com o padrão (`True`), "Café" viraria
    "Caf\u00e9" nos bytes, e o worker decodificaria errado o nome do item.
    """
    corpo = _corpo_valido()
    corpo["pedido"]["status"] = "aguardando café"

    bruto = serializar(corpo)

    assert isinstance(bruto, bytes)
    assert "café" in bruto.decode("utf-8")


# =====================================================================
# Caminhos de recusa
# =====================================================================
@pytest.mark.parametrize(
    ("mutacao", "trecho_esperado"),
    [
        # Envelope --------------------------------------------------
        pytest.param(lambda c: c.pop("versao"), "campo ausente", id="sem_versao"),
        pytest.param(lambda c: c.update(versao=2), "não suportada", id="versao_futura"),
        pytest.param(lambda c: c.update(versao="1"), "deve ser inteiro", id="versao_texto"),
        pytest.param(lambda c: c.update(evento=""), "texto não vazio", id="evento_vazio"),
        pytest.param(lambda c: c.pop("evento_id"), "campo ausente", id="sem_evento_id"),
        pytest.param(
            lambda c: c.update(origem=""), "texto não vazio", id="origem_vazia"
        ),
        pytest.param(
            lambda c: c.update(publicado_em="ontem"),
            "deve ser inteiro",
            id="publicado_em_texto",
        ),
        # Bloco pedido ----------------------------------------------
        pytest.param(lambda c: c.pop("pedido"), "campo ausente", id="sem_pedido"),
        pytest.param(
            lambda c: c.update(pedido="nao-e-objeto"),
            "não é um objeto",
            id="pedido_nao_objeto",
        ),
        pytest.param(
            lambda c: c["pedido"].update(itens=[]),
            "lista não vazia",
            id="pedido_sem_itens",
        ),
        pytest.param(
            lambda c: c["pedido"].update(itens={}),
            "lista não vazia",
            id="itens_nao_lista",
        ),
        # Itens ------------------------------------------------------
        pytest.param(
            lambda c: c["pedido"]["itens"].append("SKU-1"),
            "não é um objeto",
            id="item_nao_objeto",
        ),
        pytest.param(
            lambda c: c["pedido"]["itens"][0].update(quantidade=0),
            "deve ser >= 1",
            id="quantidade_zero",
        ),
        pytest.param(
            lambda c: c["pedido"]["itens"][0].update(quantidade=-3),
            "deve ser >= 1",
            id="quantidade_negativa",
        ),
        pytest.param(
            lambda c: c["pedido"]["itens"][0].update(quantidade=True),
            "deve ser inteiro",
            id="quantidade_bool",
        ),
        pytest.param(
            lambda c: c["pedido"]["itens"][0].update(sku=""),
            "texto não vazio",
            id="sku_vazio",
        ),
        pytest.param(
            lambda c: c["pedido"]["itens"][0].update(preco_unitario="de graça"),
            "não é decimal",
            id="preco_invalido",
        ),
        # Numéricos do pedido ---------------------------------------
        pytest.param(
            lambda c: c["pedido"].update(id="quarenta"),
            "deve ser inteiro",
            id="id_texto",
        ),
        pytest.param(
            lambda c: c["pedido"].update(total="caro"),
            "não é decimal",
            id="total_invalido",
        ),
    ],
)
def test_corpo_invalido_e_recusado_com_motivo(mutacao, trecho_esperado):
    """Cada recusa precisa dizer QUAL campo quebrou.

    A mensagem de erro é o que vai para o log e para a DLQ. Um
    "payload inválido" genérico obrigaria quem fosse tratar a mensagem a
    abrir o payload às cegas — que é justamente o que a DLQ existe para
    evitar.
    """
    corpo = _corpo_valido()
    mutacao(corpo)

    with pytest.raises(ContratoInvalido) as erro:
        validar_pedido_criado(corpo)

    assert trecho_esperado in str(erro.value)


def test_decimal_aceita_texto_numerico():
    """`"1999.90"` (texto) é um total legítimo.

    O contrato viaja por JSON, então um produtor pode mandar o número como
    texto. `Decimal(str(valor))` existe para aceitar isso; o teste trava essa
    tolerância para que uma refatoração não a trate como erro.
    """
    corpo = _corpo_valido()
    corpo["pedido"]["total"] = "1999.90"

    evento = validar_pedido_criado(corpo)

    assert str(evento.total) == "1999.90"


# =====================================================================
# Despachante
# =====================================================================
def test_despachante_roteia_pedido_criado():
    """`validar` é o que o consumidor chama.

    Testar o roteamento garante que `PedidoCriado` continua chegando ao
    validador certo pelo mesmo caminho que o worker usa em produção.
    """
    assert isinstance(validar(_corpo_valido()), PedidoCriado)


def test_despachante_recusa_corpo_nao_objeto():
    """Uma lista ou string no lugar do objeto é recusa, não iteração."""

    with pytest.raises(ContratoInvalido, match="não é um objeto"):
        validar([1, 2, 3])


def test_despachante_recusa_evento_desconhecido():
    """Evento novo deve falhar alto, não ser adivinhado.

    Um validador que aceitasse `evento` desconhecido e devolvesse um objeto
    vazio faria o consumidor registrar sucesso sem aplicar efeito — o modo
    mais silencioso de perder uma mensagem.
    """
    corpo = _corpo_valido()
    corpo["evento"] = "PedidoDesconhecidoDoFuturo"

    with pytest.raises(ContratoInvalido, match="não é suportado"):
        validar(corpo)