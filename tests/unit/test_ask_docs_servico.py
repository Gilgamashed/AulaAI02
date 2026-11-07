"""Serviço do assistente de documentação (Aula 24)."""

from __future__ import annotations

import pytest

from core.ask_docs.constantes import FRASE_GUARDRAIL
from core.ask_docs.embeddings import construir_vocabulario, serializar
from core.ask_docs.erros import IndiceVazio, ParametroInvalido
from core.ask_docs.indice import (
    ChunkIndice,
    DocumentoIndice,
    IndiceRag,
)
from core.ask_docs.servico import responder
from core.llm import LlmIndisponivel, LlmResposta

pytestmark = pytest.mark.unit


class ServicoFake:
    """Substitui o `LlmService` devolvendo um texto fixo ou levantando erro."""

    modelo = "fake"

    def __init__(self, *, texto: str = "Resposta [1]", erro: Exception | None = None):
        self._texto = texto
        self._erro = erro
        self.chamadas = 0

    def completar(self, mensagens, *, temperature, max_tokens) -> LlmResposta:
        self.chamadas += 1
        if self._erro is not None:
            raise self._erro
        return LlmResposta(texto=self._texto, tokens_prompt=10, tokens_output=5)


def _indice(tmp_path, textos: list[str]) -> IndiceRag:
    indice = IndiceRag(tmp_path / "indice.sqlite3")
    indice.inicializar()
    vocabulario = construir_vocabulario(textos)
    documento = DocumentoIndice(
        doc_id="d1",
        path="README.md",
        title="Documentação SynapseShop",
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
    return indice


def test_guardrail_nao_chama_a_llm(tmp_path):
    indice = _indice(
        tmp_path,
        ["O cache usa Redis.", "As migrações do banco rodam no startup."],
    )
    servico = ServicoFake(erro=AssertionError("não deveria ser chamado"))

    resposta = responder("Qual a capital da França?", llm=servico, indice=indice)

    assert resposta.answer == FRASE_GUARDRAIL
    assert resposta.sources == []
    assert servico.chamadas == 0


def test_resposta_traz_fontes_com_caminho_intervalo_e_score(tmp_path):
    indice = _indice(
        tmp_path,
        ["O cache usa Redis com TTL.", "As migrações do banco rodam no startup."],
    )
    servico = ServicoFake(texto="Use `python api/manage.py migrate`. [1]")

    resposta = responder("Como rodar as migrações do banco?", llm=servico, indice=indice)

    assert servico.chamadas == 1
    assert resposta.answer.startswith("Use")
    assert resposta.sources
    fonte = resposta.sources[0]
    assert fonte.path == "README.md"
    assert fonte.title == "Documentação SynapseShop"
    assert "-" in fonte.range
    assert 0.0 <= fonte.score <= 1.0
    assert fonte.score == round(fonte.score, 4)


def test_acrescenta_citacao_quando_modelo_omite(tmp_path):
    indice = _indice(tmp_path, ["As migrações do banco rodam no startup."])
    servico = ServicoFake(texto="Use o comando de migração.")

    resposta = responder("Como rodar migrações?", llm=servico, indice=indice)

    assert "Fontes:" in resposta.answer
    assert "[1]" in resposta.answer
    assert resposta.sources


def test_top_k_limita_as_fontes(tmp_path):
    indice = _indice(
        tmp_path,
        [
            "As migrações do banco rodam no startup.",
            "O banco também aceita migrações manuais.",
        ],
    )
    servico = ServicoFake(texto="Resposta [1]")

    resposta = responder(
        "migrações do banco",
        top_k=1,
        min_score=0.0,
        llm=servico,
        indice=indice,
    )

    assert len(resposta.sources) == 1


def test_indice_vazio_levanta_erro(tmp_path):
    indice = IndiceRag(tmp_path / "vazio.sqlite3")
    indice.inicializar()

    with pytest.raises(IndiceVazio):
        responder("qualquer pergunta", indice=indice)


@pytest.mark.parametrize(
    "top_k",
    [
        pytest.param(0, id="zero"),
        pytest.param(-1, id="negativo"),
        pytest.param(11, id="acima-do-maximo"),
        pytest.param(True, id="booleano"),
        pytest.param("3", id="texto"),
    ],
)
def test_top_k_invalido(tmp_path, top_k):
    indice = _indice(tmp_path, ["O cache usa Redis."])

    with pytest.raises(ParametroInvalido):
        responder("cache", top_k=top_k, indice=indice)


@pytest.mark.parametrize(
    "min_score",
    [
        pytest.param(-0.1, id="negativo"),
        pytest.param(1.1, id="acima-de-um"),
        pytest.param(True, id="booleano"),
        pytest.param("0.5", id="texto"),
    ],
)
def test_min_score_invalido(tmp_path, min_score):
    indice = _indice(tmp_path, ["O cache usa Redis."])

    with pytest.raises(ParametroInvalido):
        responder("cache", min_score=min_score, indice=indice)


def test_erro_do_provedor_propaga(tmp_path):
    indice = _indice(tmp_path, ["O cache usa Redis."])
    servico = ServicoFake(erro=LlmIndisponivel("provedor fora do ar"))

    with pytest.raises(LlmIndisponivel):
        responder("cache", llm=servico, indice=indice)
