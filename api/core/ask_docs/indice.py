"""Índice SQLite do RAG (Aula 24).

Estrutura mínima exigida pela spec — `documents` e `chunks` — mais uma tabela
interna `vocabulario` com IDF e posição de cada termo. A dimensão do vetor é o
tamanho do vocabulário, então não há colisão de hash.

A pontuação de um chunk é o maior cosseno entre o chunk inteiro e as passagens
(frases/parágrafos) dentro dele. O chunk continua sendo a unidade de citação e
o `range` devolvido é o intervalo do chunk; a passagem só refina a ordenação.
Isso é o que permite que uma pergunta específica ("como rodar migrações?")
encontre o trecho certo dentro de um chunk de ~400 tokens.

O índice é reconstruído por inteiro quando qualquer fonte muda. O corpus é
pequeno (README + OpenAPI) e a reconstrução integral mantém o IDF coerente; o
`hash` por documento evita trabalho quando nada mudou.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from .chunking import dividir_passagens
from .embeddings import Vocabulario, cosseno, desserializar
from .erros import IndiceIndisponivel

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    doc_id TEXT PRIMARY KEY,
    path TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    hash TEXT NOT NULL,
    indexed_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS chunks (
    chunk_id TEXT PRIMARY KEY,
    doc_id TEXT NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,
    chunk_text TEXT NOT NULL,
    start INTEGER NOT NULL,
    end INTEGER NOT NULL,
    embedding BLOB NOT NULL,
    dim INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_chunks_doc ON chunks(doc_id);

CREATE TABLE IF NOT EXISTS vocabulario (
    term TEXT PRIMARY KEY,
    idf REAL NOT NULL,
    indice INTEGER NOT NULL UNIQUE
);
"""


@dataclass(frozen=True)
class DocumentoIndice:
    """Linha da tabela `documents`."""

    doc_id: str
    path: str
    title: str
    hash: str
    indexed_at: str


@dataclass(frozen=True)
class ChunkIndice:
    """Linha da tabela `chunks`."""

    chunk_id: str
    doc_id: str
    chunk_text: str
    start: int
    end: int
    embedding: bytes
    dim: int


@dataclass(frozen=True)
class ResultadoBusca:
    """Chunk recuperado, já com os dados do documento e a pontuação."""

    chunk_id: str
    doc_id: str
    path: str
    title: str
    texto: str
    inicio: int
    fim: int
    score: float


class IndiceRag:
    """Acesso ao arquivo SQLite que guarda documentos, chunks e vocabulário."""

    def __init__(self, caminho: str | Path) -> None:
        self.caminho = Path(caminho)

    def inicializar(self) -> None:
        """Cria diretório, arquivo e schema de forma idempotente."""
        try:
            self.caminho.parent.mkdir(parents=True, exist_ok=True)
            with self._conexao() as conn:
                conn.executescript(SCHEMA)
        except (OSError, sqlite3.Error) as falha:
            raise IndiceIndisponivel(
                f"não foi possível inicializar o índice em '{self.caminho}': "
                f"{falha}"
            ) from falha

    def documentos(self) -> dict[str, str]:
        """Mapa `path -> hash` dos documentos atualmente indexados."""
        try:
            with self._conexao() as conn:
                linhas = conn.execute(
                    "SELECT path, hash FROM documents ORDER BY path"
                ).fetchall()
        except sqlite3.Error as falha:
            raise IndiceIndisponivel(
                f"não foi possível ler o índice em '{self.caminho}': {falha}"
            ) from falha
        return {linha["path"]: linha["hash"] for linha in linhas}

    def total_chunks(self) -> int:
        """Quantidade de chunks indexados."""
        try:
            with self._conexao() as conn:
                linha = conn.execute("SELECT COUNT(*) AS total FROM chunks").fetchone()
        except sqlite3.Error as falha:
            raise IndiceIndisponivel(
                f"não foi possível ler o índice em '{self.caminho}': {falha}"
            ) from falha
        return int(linha["total"]) if linha is not None else 0

    def carregar_vocabulario(self) -> Vocabulario:
        """IDF e posições persistidos usados para vetorizar a pergunta."""
        try:
            with self._conexao() as conn:
                linhas = conn.execute(
                    "SELECT term, idf, indice FROM vocabulario ORDER BY indice"
                ).fetchall()
        except sqlite3.Error as falha:
            raise IndiceIndisponivel(
                f"não foi possível ler o vocabulário em '{self.caminho}': {falha}"
            ) from falha
        return Vocabulario(
            idf={linha["term"]: float(linha["idf"]) for linha in linhas},
            indices={linha["term"]: int(linha["indice"]) for linha in linhas},
        )

    def substituir(
        self,
        documentos: Sequence[DocumentoIndice],
        chunks: Sequence[ChunkIndice],
        vocabulario: Vocabulario,
    ) -> None:
        """Substitui todo o conteúdo do índice numa única transação."""
        try:
            with self._conexao() as conn:
                conn.execute("DELETE FROM documents")
                conn.execute("DELETE FROM vocabulario")
                conn.executemany(
                    """
                    INSERT INTO documents (doc_id, path, title, hash, indexed_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    [
                        (doc.doc_id, doc.path, doc.title, doc.hash, doc.indexed_at)
                        for doc in documentos
                    ],
                )
                conn.executemany(
                    """
                    INSERT INTO vocabulario (term, idf, indice)
                    VALUES (?, ?, ?)
                    """,
                    [
                        (termo, vocabulario.idf[termo], posicao)
                        for termo, posicao in sorted(
                            vocabulario.indices.items(), key=lambda item: item[1]
                        )
                    ],
                )
                conn.executemany(
                    """
                    INSERT INTO chunks (
                        chunk_id, doc_id, chunk_text, start, end, embedding, dim
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            chunk.chunk_id,
                            chunk.doc_id,
                            chunk.chunk_text,
                            chunk.start,
                            chunk.end,
                            chunk.embedding,
                            chunk.dim,
                        )
                        for chunk in chunks
                    ],
                )
        except sqlite3.Error as falha:
            raise IndiceIndisponivel(
                f"não foi possível gravar o índice em '{self.caminho}': {falha}"
            ) from falha

    def buscar(
        self,
        vetor: Sequence[float],
        *,
        top_k: int,
        min_score: float,
        vocabulario: Vocabulario | None = None,
    ) -> list[ResultadoBusca]:
        """Calcula o cosseno e devolve o top-k filtrado por `min_score`."""
        try:
            with self._conexao() as conn:
                linhas = conn.execute(
                    """
                    SELECT c.chunk_id, c.doc_id, c.chunk_text, c.start, c.end,
                           c.embedding, c.dim, d.path, d.title
                    FROM chunks AS c
                    JOIN documents AS d ON d.doc_id = c.doc_id
                    ORDER BY c.chunk_id
                    """
                ).fetchall()
        except sqlite3.Error as falha:
            raise IndiceIndisponivel(
                f"não foi possível consultar o índice em '{self.caminho}': {falha}"
            ) from falha

        resultados: list[ResultadoBusca] = []
        for linha in linhas:
            embedding = desserializar(linha["embedding"], dim=int(linha["dim"]))
            score = cosseno(vetor, embedding)
            if vocabulario is not None:
                for passagem in dividir_passagens(linha["chunk_text"]):
                    score = max(
                        score,
                        cosseno(vetor, vocabulario.vetorizar(passagem)),
                    )
            if score < min_score:
                continue
            resultados.append(
                ResultadoBusca(
                    chunk_id=linha["chunk_id"],
                    doc_id=linha["doc_id"],
                    path=linha["path"],
                    title=linha["title"],
                    texto=linha["chunk_text"],
                    inicio=int(linha["start"]),
                    fim=int(linha["end"]),
                    score=score,
                )
            )

        resultados.sort(key=lambda item: (-item.score, item.chunk_id))
        return resultados[:top_k]

    @contextmanager
    def _conexao(self) -> Iterator[sqlite3.Connection]:
        conexao = sqlite3.connect(self.caminho)
        conexao.row_factory = sqlite3.Row
        conexao.execute("PRAGMA foreign_keys = ON")
        try:
            yield conexao
            conexao.commit()
        except Exception:
            conexao.rollback()
            raise
        finally:
            conexao.close()
