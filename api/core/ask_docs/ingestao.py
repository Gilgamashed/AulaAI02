"""Pipeline de ingestão do RAG (Aula 24).

Responsabilidades:

1. ler as fontes configuradas (por padrão `README.md` e `docs/openapi.yaml`);
2. calcular o hash de cada documento para evitar reindexação desnecessária;
3. dividir em chunks de ~400 tokens com overlap de ~80;
4. calcular IDF e embeddings locais de cada chunk;
5. substituir o índice SQLite de forma atômica.

Quando qualquer fonte muda, o índice inteiro é reconstruído. O corpus é pequeno
e isso mantém o IDF consistente com todos os vetores gravados.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Iterable

from django.conf import settings

from .chunking import Bloco, dividir
from .embeddings import construir_vocabulario, serializar
from .erros import DocumentoNaoEncontrado, IngestaoFalhou
from .indice import ChunkIndice, DocumentoIndice, IndiceRag

TITULO_MARKDOWN = re.compile(r"^#\s+(.+)$", re.MULTILINE)
TITULO_YAML = re.compile(r"^\s{2}title:\s*(.+)$", re.MULTILINE)


@dataclass(frozen=True)
class DocumentoIngerido:
    """Resumo de um documento processado."""

    path: str
    title: str
    hash: str
    chunks: int


@dataclass(frozen=True)
class ResultadoIngestao:
    """Resumo da execução do pipeline."""

    documentos: list[DocumentoIngerido]
    chunks: int
    reindexado: bool


def indexar(
    *,
    raiz: str | Path | None = None,
    fontes: Iterable[str] | str | None = None,
    forcar: bool = False,
    indice: IndiceRag | None = None,
) -> ResultadoIngestao:
    """Executa a ingestão completa e devolve o resumo do índice."""
    raiz_path = Path(raiz or settings.BASE_DIR.parent).resolve()
    fontes_tuple = _fontes(fontes)
    if not fontes_tuple:
        raise IngestaoFalhou("nenhuma fonte de documentação foi configurada")

    indice = indice or IndiceRag(settings.ASK_DOCS_INDEX_PATH)
    indice.inicializar()

    brutos = [_ler_fonte(raiz_path, fonte) for fonte in fontes_tuple]
    desejado = {path: hash_conteudo for path, _, _, hash_conteudo in brutos}

    existentes = indice.documentos()
    if not forcar and existentes == desejado and indice.total_chunks() > 0:
        return ResultadoIngestao(
            documentos=[],
            chunks=indice.total_chunks(),
            reindexado=False,
        )

    tokens = int(getattr(settings, "ASK_DOCS_CHUNK_TOKENS", 400))
    overlap = int(getattr(settings, "ASK_DOCS_CHUNK_OVERLAP", 80))

    blocos_por_path: dict[str, list[Bloco]] = {}
    for path, _, texto, _ in brutos:
        blocos = dividir(texto, tokens=tokens, overlap=overlap)
        if not blocos:
            raise IngestaoFalhou(f"documento sem conteúdo indexável: {path}")
        blocos_por_path[path] = blocos

    todos_textos = [
        bloco.texto for blocos in blocos_por_path.values() for bloco in blocos
    ]
    vocabulario = construir_vocabulario(todos_textos)

    agora = datetime.now(timezone.utc).isoformat()
    documentos_indice: list[DocumentoIndice] = []
    chunks_indice: list[ChunkIndice] = []
    documentos_ingeridos: list[DocumentoIngerido] = []

    for path, title, _, hash_conteudo in brutos:
        doc_id = _doc_id(path)
        documentos_indice.append(
            DocumentoIndice(
                doc_id=doc_id,
                path=path,
                title=title,
                hash=hash_conteudo,
                indexed_at=agora,
            )
        )
        blocos = blocos_por_path[path]
        for bloco in blocos:
            vetor = vocabulario.vetorizar(bloco.texto)
            chunks_indice.append(
                ChunkIndice(
                    chunk_id=f"{doc_id}:{bloco.indice:04d}",
                    doc_id=doc_id,
                    chunk_text=bloco.texto,
                    start=bloco.inicio,
                    end=bloco.fim,
                    embedding=serializar(vetor),
                    dim=vocabulario.dim,
                )
            )
        documentos_ingeridos.append(
            DocumentoIngerido(
                path=path,
                title=title,
                hash=hash_conteudo,
                chunks=len(blocos),
            )
        )

    indice.substituir(documentos_indice, chunks_indice, vocabulario)
    return ResultadoIngestao(
        documentos=documentos_ingeridos,
        chunks=len(chunks_indice),
        reindexado=True,
    )


def _fontes(fontes: Iterable[str] | str | None) -> tuple[str, ...]:
    if fontes is None:
        return tuple(getattr(settings, "ASK_DOCS_SOURCES", ()))
    if isinstance(fontes, str):
        return (fontes,)
    return tuple(fontes)


def _ler_fonte(raiz: Path, fonte: str) -> tuple[str, str, str, str]:
    caminho = (raiz / fonte).resolve()
    if not caminho.is_relative_to(raiz):
        raise IngestaoFalhou(
            f"a fonte '{fonte}' aponta para fora da raiz do projeto"
        )
    if not caminho.is_file():
        raise DocumentoNaoEncontrado(f"documento não encontrado: {fonte}")

    try:
        texto = caminho.read_text(encoding="utf-8")
    except OSError as falha:
        raise DocumentoNaoEncontrado(
            f"não foi possível ler o documento '{fonte}': {falha}"
        ) from falha

    path = PurePosixPath(fonte.replace("\\", "/")).as_posix()
    hash_conteudo = hashlib.sha256(texto.encode("utf-8")).hexdigest()
    return path, _titulo(path, texto), texto, hash_conteudo


def _titulo(path: str, texto: str) -> str:
    if path.endswith(".md"):
        encontrado = TITULO_MARKDOWN.search(texto)
        if encontrado is not None:
            return encontrado.group(1).strip()
    if path.endswith((".yaml", ".yml")):
        encontrado = TITULO_YAML.search(texto)
        if encontrado is not None:
            return encontrado.group(1).strip().strip("\"'")
    nome = PurePosixPath(path).name
    return nome or path


def _doc_id(path: str) -> str:
    return hashlib.sha256(path.encode("utf-8")).hexdigest()[:16]
