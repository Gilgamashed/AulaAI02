"""Ingestão do RAG (Aula 24): hash, fontes e chunking configurável."""

from __future__ import annotations

import pytest

from core.ask_docs.erros import DocumentoNaoEncontrado, IngestaoFalhou
from core.ask_docs.indice import IndiceRag
from core.ask_docs.ingestao import indexar

pytestmark = pytest.mark.unit

README = """\
# README de Teste

O cache usa Redis com TTL de sessenta segundos.

## Migrações

As migrações do banco rodam no startup da API.
"""

OPENAPI = """\
openapi: 3.1.0
info:
  title: API de Teste
  version: 1.0.0
paths: {}
"""


def _projeto(tmp_path, *, readme: str = README, openapi: str = OPENAPI):
    (tmp_path / "README.md").write_text(readme, encoding="utf-8")
    docs = tmp_path / "docs"
    docs.mkdir(exist_ok=True)
    (docs / "openapi.yaml").write_text(openapi, encoding="utf-8")


def _indice(tmp_path):
    return IndiceRag(tmp_path / "indice.sqlite3")


def test_indexa_readme_e_openapi(tmp_path):
    _projeto(tmp_path)
    indice = _indice(tmp_path)

    resultado = indexar(
        raiz=tmp_path,
        fontes=["README.md", "docs/openapi.yaml"],
        indice=indice,
    )

    assert resultado.reindexado is True
    assert [documento.path for documento in resultado.documentos] == [
        "README.md",
        "docs/openapi.yaml",
    ]
    assert resultado.documentos[0].title == "README de Teste"
    assert resultado.documentos[1].title == "API de Teste"
    assert resultado.chunks == indice.total_chunks()
    assert resultado.chunks >= 2


def test_segunda_execucao_sem_mudanca_nao_reindexa(tmp_path):
    _projeto(tmp_path)
    indice = _indice(tmp_path)

    primeira = indexar(
        raiz=tmp_path,
        fontes=["README.md", "docs/openapi.yaml"],
        indice=indice,
    )
    segunda = indexar(
        raiz=tmp_path,
        fontes=["README.md", "docs/openapi.yaml"],
        indice=indice,
    )

    assert primeira.reindexado is True
    assert segunda.reindexado is False
    assert segunda.chunks == primeira.chunks


def test_mudanca_de_conteudo_reindexa(tmp_path):
    _projeto(tmp_path)
    indice = _indice(tmp_path)
    indexar(raiz=tmp_path, fontes=["README.md"], indice=indice)

    (tmp_path / "README.md").write_text(
        "# README de Teste\n\nAgora com uma linha nova sobre a DLQ.",
        encoding="utf-8",
    )
    resultado = indexar(raiz=tmp_path, fontes=["README.md"], indice=indice)

    assert resultado.reindexado is True


def test_force_reindexa_mesmo_sem_mudanca(tmp_path):
    _projeto(tmp_path)
    indice = _indice(tmp_path)
    indexar(raiz=tmp_path, fontes=["README.md"], indice=indice)

    resultado = indexar(
        raiz=tmp_path,
        fontes=["README.md"],
        forcar=True,
        indice=indice,
    )

    assert resultado.reindexado is True


def test_fonte_ausente(tmp_path):
    with pytest.raises(DocumentoNaoEncontrado):
        indexar(
            raiz=tmp_path,
            fontes=["README.md"],
            indice=_indice(tmp_path),
        )


def test_fonte_fora_da_raiz(tmp_path):
    with pytest.raises(IngestaoFalhou):
        indexar(
            raiz=tmp_path,
            fontes=["../fora.md"],
            indice=_indice(tmp_path),
        )


def test_documento_vazio_falha(tmp_path):
    _projeto(tmp_path, readme="   \n\n")

    with pytest.raises(IngestaoFalhou):
        indexar(
            raiz=tmp_path,
            fontes=["README.md"],
            indice=_indice(tmp_path),
        )


def test_chunking_usa_configuracao_de_settings(tmp_path, settings):
    settings.ASK_DOCS_CHUNK_TOKENS = 10
    settings.ASK_DOCS_CHUNK_OVERLAP = 2
    _projeto(tmp_path, readme="# Teste\n\n" + " ".join(f"t{i}" for i in range(25)))

    resultado = indexar(
        raiz=tmp_path,
        fontes=["README.md"],
        indice=_indice(tmp_path),
    )

    assert resultado.documentos[0].chunks == 4


def test_fonte_unica_em_string(tmp_path):
    _projeto(tmp_path)

    resultado = indexar(
        raiz=tmp_path,
        fontes="README.md",
        indice=_indice(tmp_path),
    )

    assert [documento.path for documento in resultado.documentos] == ["README.md"]


def test_sem_fontes_configuradas_falha(tmp_path):
    with pytest.raises(IngestaoFalhou):
        indexar(
            raiz=tmp_path,
            fontes=[],
            indice=_indice(tmp_path),
        )
