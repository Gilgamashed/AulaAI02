"""Erros do assistente de documentação (Aula 24)."""

from __future__ import annotations


class AskDocsErro(Exception):
    """Base dos erros previsíveis do RAG."""


class DocumentoNaoEncontrado(AskDocsErro):
    """Uma fonte configurada não existe ou não pode ser lida."""


class IngestaoFalhou(AskDocsErro):
    """A ingestão não pôde produzir um índice consistente."""


class IndiceIndisponivel(AskDocsErro):
    """O arquivo SQLite do índice não pôde ser aberto/escrito."""


class IndiceVazio(AskDocsErro):
    """Ainda não há chunks indexados para consultar."""


class ParametroInvalido(AskDocsErro):
    """`top_k` ou `min_score` fora dos limites aceitos."""
