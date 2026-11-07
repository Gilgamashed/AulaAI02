"""Índice SQLite do RAG (Aula 24)."""

from __future__ import annotations

import pytest

from core.ask_docs.embeddings import construir_vocabulario, serializar
from core.ask_docs.erros import IndiceIndisponivel
from core.ask_docs.indice import (
    ChunkIndice,
    DocumentoIndice,
    IndiceRag,
)


def _montar(tmp_path, textos: list[str]) -> tuple[IndiceRag, object]:
    indice = IndiceRag(tmp_path / "indice.sqlite3")
    indice.inicializar()
    vocabulario = construir_vocabulario(textos)
    documento = DocumentoIndice(
        doc_id="d1",
        path="README.md",
        title="Documentação",
        hash="hash-1",
        indexed_at="2026-11-06T00:00:00+00:00",
    )
    chunks = [
        ChunkIndice(
            chunk_id=f"d1:{posicao:04d}",
            doc_id="d1",
            chunk_text=texto,
            start=0,
            end=len(texto),
            embedding=serializar(vocabulario.vetorizar(texto)),
            dim=vocabulario.dim,
        )
        for posicao, texto in enumerate(textos)
    ]
    indice.substituir([documento], chunks, vocabulario)
    return indice, vocabulario


pytestmark = pytest.mark.unit


def test_inicializar_e_idempotente(tmp_path):
    indice = IndiceRag(tmp_path / "indice.sqlite3")

    indice.inicializar()
    indice.inicializar()

    assert indice.total_chunks() == 0
    assert indice.documentos() == {}


def test_substituir_e_ler_documentos_chunks_e_vocabulario(tmp_path):
    indice, vocabulario = _montar(
        tmp_path,
        [
            "As migrações do banco rodam no startup.",
            "O cache usa Redis com TTL.",
        ],
    )

    assert indice.documentos() == {"README.md": "hash-1"}
    assert indice.total_chunks() == 2
    assert indice.carregar_vocabulario().dim == vocabulario.dim


def test_substituir_remove_conteudo_anterior(tmp_path):
    indice, _ = _montar(tmp_path, ["conteúdo antigo sobre cache"])
    _, novo_vocabulario = _montar(tmp_path, ["conteúdo novo sobre migrações"])

    assert indice.documentos() == {"README.md": "hash-1"}
    assert indice.total_chunks() == 1
    assert indice.carregar_vocabulario().dim == novo_vocabulario.dim


def test_buscar_ordena_por_cosseno_e_limita_top_k(tmp_path):
    indice, vocabulario = _montar(
        tmp_path,
        [
            "As migrações do banco rodam no startup da API.",
            "O cache usa Redis com TTL de sessenta segundos.",
            "A DLQ do Kafka guarda mensagens que falharam.",
        ],
    )
    pergunta = vocabulario.vetorizar("Como rodar as migrações do banco?")

    resultados = indice.buscar(
        pergunta,
        top_k=2,
        min_score=0.0,
        vocabulario=vocabulario,
    )

    assert len(resultados) == 2
    assert "migrações" in resultados[0].texto
    assert resultados[0].score >= resultados[1].score


def test_buscar_filtra_pelo_min_score(tmp_path):
    indice, vocabulario = _montar(tmp_path, ["O cache usa Redis."])
    pergunta = vocabulario.vetorizar("Redis")

    assert (
        indice.buscar(pergunta, top_k=3, min_score=0.99, vocabulario=vocabulario)
        == []
    )


def test_buscar_sem_vocabulario_usa_apenas_o_chunk(tmp_path):
    indice, vocabulario = _montar(
        tmp_path,
        ["O cache usa Redis. As migrações do banco rodam no startup."],
    )
    pergunta = vocabulario.vetorizar("migrações do banco")

    sem_refino = indice.buscar(pergunta, top_k=1, min_score=0.0)
    com_refino = indice.buscar(
        pergunta,
        top_k=1,
        min_score=0.0,
        vocabulario=vocabulario,
    )

    assert com_refino[0].score > sem_refino[0].score


def test_buscar_devolve_intervalo_e_titulo(tmp_path):
    indice, vocabulario = _montar(tmp_path, ["O cache usa Redis."])
    pergunta = vocabulario.vetorizar("cache")

    [resultado] = indice.buscar(
        pergunta,
        top_k=1,
        min_score=0.0,
        vocabulario=vocabulario,
    )

    assert resultado.path == "README.md"
    assert resultado.title == "Documentação"
    assert resultado.inicio == 0
    assert resultado.fim == len("O cache usa Redis.")


def test_indice_indisponivel_quando_caminho_e_diretorio(tmp_path):
    caminho = tmp_path / "diretorio"
    caminho.mkdir()

    with pytest.raises(IndiceIndisponivel):
        IndiceRag(caminho).inicializar()


def test_buscar_com_vetor_de_dimensao_errada_levanta_erro(tmp_path):
    indice, _ = _montar(tmp_path, ["O cache usa Redis."])

    with pytest.raises(ValueError):
        indice.buscar([1.0, 0.0], top_k=1, min_score=0.0)
