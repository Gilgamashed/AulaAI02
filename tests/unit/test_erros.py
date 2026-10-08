"""Testes unitários de `erros.descrever` (Aula 12).

Este módulo existe por causa de um defeito real: exceções do `pika` e do
`confluent_kafka` são frequentemente levantadas **sem argumentos**, então
`str(exc)` devolve `""` e o log ficava

    {"evento": "WorkerSemConexao", "erro": "", ...}

— um log transacional parecendo que não tinha erro nenhum. A regra do módulo é
que o **tipo** sempre entra no log.

O teste de `ValueError()` sem argumento não é recesso: ele é a regressão
exata do defeito que motivou o módulo.
"""

import pytest

from core.messaging.erros import descrever

pytestmark = pytest.mark.unit


def test_excecao_com_mensagem_traz_tipo_e_texto():
    assert descrever(RuntimeError("broker indisponível")) == (
        "RuntimeError: broker indisponível"
    )


def test_excecao_sem_argumentos_ainda_revela_o_tipo():
    """O caso que originou o módulo.

    Sem argumentos, `str(exc)` é `""`. Se a função devolvesse isso, o log
    diria que não houve erro — que é o oposto do que um log precisa.
    """
    assert descrever(ValueError()) == "ValueError"


def test_mensagem_so_com_espacos_e_tratada_como_vazia():
    """Espaço em branco é ruído, não informação.

    Sem o `.strip()`, o log levaria `TypeError:    ` — com aparência de
    mensagem e nenhuma informação dentro.
    """
    assert descrever(TypeError("    ")) == "TypeError"


def test_mensagem_com_espacos_ao_redor_e_aparada():
    """A mensagem preservada não deve vir com padding do log.

    O `.strip()` é o que faz isso. Num log JSON o padding é invisível a olho nu,
    mas numa comparação de texto ou numa leitura de coluna do banco ele conta.
    """
    assert descrever(RuntimeError("  broker fora  ")) == "RuntimeError: broker fora"


@pytest.mark.parametrize(
    ("excecao", "esperado"),
    [
        pytest.param(TimeoutError(), "TimeoutError", id="timeout"),
        pytest.param(ConnectionError(), "ConnectionError", id="conexao"),
        pytest.param(KeyboardInterrupt(), "KeyboardInterrupt", id="interrupcao"),
        # Exceção aninhada: o `str()` do embrulho é o da causa (o Python
        # repassa o argumento para `Exception.__init__`), então o relatório
        # mostra o tipo de fora com a mensagem de dentro. É a informação útil:
        # qual tipo o código esperava e o que aconteceu de fato.
        pytest.param(
            RuntimeError(ValueError("timeout na conexão")),
            "RuntimeError: timeout na conexão",
            id="aninhada",
        ),
    ],
)
def test_relatorio_traz_tipo_e_mensagem_util(excecao, esperado):
    assert descrever(excecao) == esperado


def test_texto_com_quebra_de_linha_sobrevive():
    """A mensagem pode ter várias linhas; o log tem de aceitar.

    O motivo de falha vai para o log e para a coluna `motivo_falha` do
    pedido, então não pode ser truncado nem normalizado aqui.
    """
    resultado = descrever(RuntimeError("linha 1\nlinha 2"))

    assert resultado.startswith("RuntimeError: ")
    assert "linha 2" in resultado