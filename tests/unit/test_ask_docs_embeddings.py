"""Embeddings locais e cosseno do RAG (Aula 24)."""

from __future__ import annotations

import math

import pytest

from core.ask_docs.embeddings import (
    Vocabulario,
    calcular_idf,
    construir_vocabulario,
    cosseno,
    desserializar,
    serializar,
)

pytestmark = pytest.mark.unit


def _norma(vetor) -> float:
    return math.sqrt(math.fsum(valor * valor for valor in vetor))


def test_vocabulario_exclui_stopwords_e_indexa_termos():
    vocabulario = construir_vocabulario(
        [
            "Como rodar as migrações do banco de dados",
            "O cache usa Redis e o banco usa PostgreSQL",
        ]
    )

    assert "como" not in vocabulario.indices
    assert "o" not in vocabulario.indices
    assert {"migracoes", "banco", "dados", "cache", "redis"} <= set(
        vocabulario.indices
    )
    assert vocabulario.dim == len(vocabulario.indices)
    assert sorted(vocabulario.indices.values()) == list(range(vocabulario.dim))


def test_vetor_e_deterministico_e_normalizado():
    vocabulario = construir_vocabulario(["migrações do banco de dados"])
    texto = "Como rodar as migrações do banco de dados?"

    primeiro = vocabulario.vetorizar(texto)
    segundo = vocabulario.vetorizar(texto)

    assert primeiro == segundo
    assert math.isclose(_norma(primeiro), 1.0, rel_tol=1e-5)


def test_texto_relacionado_tem_cosseno_maior():
    vocabulario = construir_vocabulario(
        [
            "As migrações do banco rodam no startup da API.",
            "O cache usa Redis com TTL de sessenta segundos.",
        ]
    )
    pergunta = vocabulario.vetorizar("Como rodar migrações do banco?")
    relacionado = vocabulario.vetorizar(
        "As migrações do banco rodam no startup da API."
    )
    nao_relacionado = vocabulario.vetorizar(
        "O cache usa Redis com TTL de sessenta segundos."
    )

    assert cosseno(pergunta, relacionado) > cosseno(pergunta, nao_relacionado)


def test_termo_desconhecido_gera_vetor_zero():
    vocabulario = construir_vocabulario(["O cache usa Redis."])

    vetor = vocabulario.vetorizar("kubernetes e grafana")

    assert _norma(vetor) == 0.0
    assert cosseno(vetor, vocabulario.vetorizar("cache redis")) == 0.0


def test_vocabulario_vazio_nao_quebra():
    vocabulario = construir_vocabulario([])

    assert vocabulario.dim == 0
    assert _norma(vocabulario.vetorizar("qualquer coisa")) == 0.0


def test_max_termos_invalido():
    vocabulario = construir_vocabulario(["cache redis"])

    with pytest.raises(ValueError):
        vocabulario.vetorizar("cache", max_termos=0)


def test_cosseno_clampa_e_valida_dimensao():
    assert cosseno([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)
    assert cosseno([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)
    assert cosseno([-1.0, 0.0], [1.0, 0.0]) == pytest.approx(0.0)

    with pytest.raises(ValueError):
        cosseno([1.0], [1.0, 2.0])


def test_serializacao_roundtrip_e_dimensao_errada():
    vetor = [0.5, 0.25, 0.75]

    blob = serializar(vetor)
    recuperado = desserializar(blob, dim=3)

    assert list(recuperado) == pytest.approx(vetor, rel=1e-6)
    with pytest.raises(ValueError):
        desserializar(blob, dim=4)


def test_calcular_idf_vazio():
    assert calcular_idf([]) == {}


def test_vocabulario_tem_idf_para_todos_os_termos():
    vocabulario = construir_vocabulario(["cache redis", "cache banco"])

    assert set(vocabulario.idf) == set(vocabulario.indices)
    assert vocabulario.idf["cache"] <= vocabulario.idf["redis"]


def test_vocabulario_dataclass_pode_ser_vazio():
    vocabulario = Vocabulario()

    assert vocabulario.dim == 0
    assert _norma(vocabulario.vetorizar("cache")) == 0.0
