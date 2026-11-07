"""Chunking do RAG (Aula 24): ~400 tokens com overlap de ~80."""

from __future__ import annotations

import pytest

from core.ask_docs.chunking import dividir, dividir_passagens

pytestmark = pytest.mark.unit


def _texto(tokens: int) -> str:
    return " ".join(f"t{i}" for i in range(tokens))


def test_texto_vazio_nao_gera_blocos():
    assert dividir("") == []
    assert dividir("   \n\t ") == []


def test_texto_curto_gera_um_unico_bloco():
    texto = "uma frase curta para indexar"

    blocos = dividir(texto, tokens=400, overlap=80)

    assert len(blocos) == 1
    assert blocos[0].texto == texto
    assert blocos[0].inicio == 0
    assert blocos[0].fim == len(texto)


def test_cadencia_400_80_e_offsets_de_caractere():
    texto = _texto(1000)

    blocos = dividir(texto, tokens=400, overlap=80)

    assert len(blocos) == 3
    for bloco in blocos:
        assert texto[bloco.inicio : bloco.fim] == bloco.texto

    tokens_por_bloco = [bloco.texto.split() for bloco in blocos]
    assert [len(tokens) for tokens in tokens_por_bloco] == [400, 400, 360]
    assert tokens_por_bloco[0][-80:] == tokens_por_bloco[1][:80]
    assert tokens_por_bloco[1][-80:] == tokens_por_bloco[2][:80]


def test_ultimo_bloco_termina_no_fim_do_documento():
    texto = _texto(401)

    blocos = dividir(texto, tokens=400, overlap=80)

    assert len(blocos) == 2
    assert blocos[-1].fim == len(texto)
    assert bloco_termina(blocos[-1], texto)


def bloco_termina(bloco, texto: str) -> bool:
    return bloco.texto == texto[bloco.inicio : bloco.fim]


def test_unicode_mantem_offsets():
    texto = "Configuração de migração: ação, coração e informação."

    blocos = dividir(texto, tokens=3, overlap=1)

    assert blocos
    for bloco in blocos:
        assert texto[bloco.inicio : bloco.fim] == bloco.texto


@pytest.mark.parametrize(
    "tokens,overlap",
    [
        pytest.param(0, 0, id="tokens-zero"),
        pytest.param(-1, 0, id="tokens-negativo"),
        pytest.param(10, -1, id="overlap-negativo"),
        pytest.param(10, 10, id="overlap-igual"),
        pytest.param(10, 11, id="overlap-maior"),
    ],
)
def test_parametros_invalidos(tokens, overlap):
    with pytest.raises(ValueError):
        dividir("texto", tokens=tokens, overlap=overlap)


def test_dividir_passagens_por_frase_e_paragrafo():
    texto = (
        "O cache usa Redis. As migrações rodam no startup.\n\n"
        "Curto.\n"
        "A DLQ guarda mensagens que falharam depois das reentregas."
    )

    passagens = dividir_passagens(texto)

    assert "O cache usa Redis." in passagens
    assert "As migrações rodam no startup." in passagens
    assert "Curto." not in passagens
    assert "A DLQ guarda mensagens que falharam depois das reentregas." in passagens
