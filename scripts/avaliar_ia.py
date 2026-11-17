"""Avaliação do golden set dos pilares de IA (fase 2, spec 01).

O script mede, contra a stack já em execução, a taxa de sucesso de
`/ask_sql/`, `/ask_docs/` e `/assist/` por categoria. Ele **não corrige**
nada: o valor está em produzir um baseline reproduzível, com taxonomia de
falhas, latência e consumo de tokens.

Decisões:

- somente biblioteca padrão (`urllib`, `json`, `argparse`), como
  `scripts/validar_mvp.py`;
- o cliente HTTP não levanta em status inesperado: a avaliação precisa
  classificar o 4xx/5xx, não abortar no primeiro item;
- expectativas são estruturais (status, colunas, linhas, fontes), nunca o SQL
  exato — o modelo pode escolher aliases diferentes;
- `recusa_esperada` e `guardrail_esperado` contam como comportamento correto;
- o gate de saída considera apenas `consulta` (texto-para-SQL) e
  `rag_tecnico`; `/assist` é informativo;
- o access token expira em 5 minutos; ao receber 401, o harness renova o
  login e repete o item uma vez, sem imprimir token nem senha.

Uso:

    python scripts/avaliar_ia.py --dry-run
    python scripts/avaliar_ia.py --min-sucesso 0
    python scripts/avaliar_ia.py --categorias join,jsonb_itens --delay 1.0

As credenciais vêm de `--usuario`/`--senha` ou das variáveis
`AVALIACAO_IA_USUARIO`/`AVALIACAO_IA_SENHA` (com fallback para `SEED_ADMIN_*`).
Senha e token nunca são impressos.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import unicodedata
import urllib.error
import urllib.request
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BASE_URL_PADRAO = "http://localhost:8000"
GOLDEN_SET_PADRAO = Path("scripts/avaliacao_ia/golden_set.json")
SAIDA_PADRAO = Path("docs/portfolio/evidencias/ia")
TIMEOUT_PADRAO = 60.0
DELAY_PADRAO = 0.5
MIN_SUCESSO_PADRAO = 0.8
MAX_CARACTERES_PERGUNTA = 500
MIN_CI_MOCK = 20
MIN_FORA_MOCK = 10
FRASE_GUARDRAIL = "não encontrei essa informação"

ENDERECO_SQL = "/api/v1/ask_sql/"
ENDERECO_DOCS = "/api/v1/ask_docs/"
ENDERECO_ASSIST = "/api/v1/assist/"
ENDERECOS = frozenset({ENDERECO_SQL, ENDERECO_DOCS, ENDERECO_ASSIST})

CATEGORIAS_MINIMOS: dict[str, int] = {
    "contagem": 4,
    "listagem": 4,
    "agregacao": 6,
    "serie_temporal": 5,
    "join": 5,
    "jsonb_itens": 5,
    "ranking": 4,
    "fora_dominio": 4,
    "rag_tecnico": 6,
    "rag_fora_corpus": 3,
}
CATEGORIAS_EXTRAS = frozenset({"assist"})
CATEGORIAS = frozenset(CATEGORIAS_MINIMOS) | CATEGORIAS_EXTRAS
ORDEM_CATEGORIAS = tuple(CATEGORIAS_MINIMOS) + tuple(sorted(CATEGORIAS_EXTRAS))

TIPOS_RESULTADO = frozenset(
    {"consulta", "recusa_esperada", "guardrail_esperado", "rag_tecnico", "assist"}
)
ENDERECO_POR_TIPO = {
    "consulta": ENDERECO_SQL,
    "recusa_esperada": ENDERECO_SQL,
    "guardrail_esperado": ENDERECO_DOCS,
    "rag_tecnico": ENDERECO_DOCS,
    "assist": ENDERECO_ASSIST,
}

TAXONOMIA = (
    "auth",
    "http_4xx_inesperado",
    "http_5xx",
    "indice_ausente",
    "nao_suportado",
    "sql_proibido",
    "sql_invalido",
    "execucao_falhou",
    "sem_fonte",
    "sem_citacao",
    "resposta_vazia",
    "timeout",
    "resposta_inesperada",
)


class GoldenSetInvalido(ValueError):
    """O golden set não atende ao contrato da spec 01."""


class FalhaRede(RuntimeError):
    """A chamada HTTP não chegou a produzir uma resposta."""


class ErroAuth(RuntimeError):
    """O login demonstrativo falhou."""


@dataclass(frozen=True)
class Resposta:
    """Resposta HTTP crua, inclusive de erro."""

    status: int
    dados: Any
    texto: str


@dataclass
class Classificacao:
    """Resultado da avaliação de um item, antes de agregar."""

    sucesso: bool
    falha: str | None
    detalhe: str
    colunas: list[str]
    linhas: int = 0
    fontes: int = 0
    tokens_prompt: int = 0
    tokens_output: int = 0


@dataclass
class ResultadoItem:
    """Linha do relatório para um item do golden set."""

    id: str
    categoria: str
    endpoint: str
    tipo_resultado: str
    pergunta: str
    status_http: int | None
    sucesso: bool
    falha: str | None
    detalhe: str
    latencia_ms: float
    colunas: list[str]
    linhas: int
    fontes: int
    tokens_prompt: int
    tokens_output: int


class ClienteHttp:
    """Cliente HTTP mínimo que devolve 4xx/5xx em vez de levantar."""

    def __init__(self, base_url: str, timeout: float = TIMEOUT_PADRAO) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def requisitar(
        self,
        metodo: str,
        caminho: str,
        *,
        corpo: Any | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> Resposta:
        url = (
            caminho
            if caminho.startswith("http")
            else self.base_url + "/" + caminho.lstrip("/")
        )
        dados = None
        cabecalhos = {"Accept": "application/json", **(headers or {})}
        if corpo is not None:
            dados = json.dumps(corpo).encode("utf-8")
            cabecalhos.setdefault("Content-Type", "application/json")
        requisicao = urllib.request.Request(
            url, data=dados, headers=cabecalhos, method=metodo.upper()
        )
        try:
            with urllib.request.urlopen(requisicao, timeout=self.timeout) as resposta:
                status = int(resposta.status)
                texto = resposta.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            status = int(exc.code)
            texto = exc.read().decode("utf-8", errors="replace")
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise FalhaRede(_resumir_texto(exc)) from exc

        try:
            dados_json = json.loads(texto) if texto else None
        except ValueError:
            dados_json = None
        return Resposta(status=status, dados=dados_json, texto=texto)


# =====================================================================
# Golden set
# =====================================================================
def carregar_golden_set(caminho: str | Path) -> dict[str, Any]:
    """Lê e valida o golden set; devolve o dicionário bruto."""
    try:
        bruto = Path(caminho).read_text(encoding="utf-8")
    except OSError as exc:
        raise GoldenSetInvalido(f"não foi possível ler {caminho}: {exc}") from exc
    try:
        dados = json.loads(bruto)
    except ValueError as exc:
        raise GoldenSetInvalido(f"JSON inválido em {caminho}: {exc}") from exc
    validar_golden_set(dados)
    return dados


def validar_golden_set(dados: Any) -> None:
    """Aplica o contrato da spec 01 antes de qualquer chamada HTTP."""
    if not isinstance(dados, dict):
        raise GoldenSetInvalido("o golden set deve ser um objeto JSON")
    if not isinstance(dados.get("versao"), int):
        raise GoldenSetInvalido("campo 'versao' deve ser inteiro")
    itens = dados.get("itens")
    if not isinstance(itens, list) or not itens:
        raise GoldenSetInvalido("campo 'itens' deve ser uma lista não vazia")

    ids: set[str] = set()
    contagem: Counter[str] = Counter()
    ci_mock = 0
    fora_mock = 0

    for posicao, item in enumerate(itens, start=1):
        _validar_item(item, posicao=posicao, ids=ids)
        contagem[item["categoria"]] += 1
        tags = {str(tag) for tag in item["tags"]}
        if "ci_mock" in tags:
            ci_mock += 1
        elif (
            item["tipo_resultado"] == "consulta"
            and item["endpoint"] == ENDERECO_SQL
        ):
            fora_mock += 1

    for categoria, minimo in CATEGORIAS_MINIMOS.items():
        if contagem[categoria] < minimo:
            raise GoldenSetInvalido(
                f"categoria '{categoria}' tem {contagem[categoria]} itens; "
                f"o mínimo é {minimo}"
            )
    if ci_mock < MIN_CI_MOCK:
        raise GoldenSetInvalido(
            f"o golden set tem {ci_mock} itens 'ci_mock'; o mínimo é {MIN_CI_MOCK}"
        )
    if fora_mock < MIN_FORA_MOCK:
        raise GoldenSetInvalido(
            f"o golden set tem {fora_mock} consultas fora do mock; "
            f"o mínimo é {MIN_FORA_MOCK}"
        )


def _validar_item(item: Any, *, posicao: int, ids: set[str]) -> None:
    rotulo = f"item {posicao}"
    if not isinstance(item, dict):
        raise GoldenSetInvalido(f"{rotulo} não é um objeto")
    for campo in (
        "id",
        "categoria",
        "endpoint",
        "pergunta",
        "tipo_resultado",
        "esperado",
        "tags",
    ):
        if campo not in item:
            raise GoldenSetInvalido(f"{rotulo} sem o campo '{campo}'")

    identificador = item["id"]
    if not isinstance(identificador, str) or not identificador.strip():
        raise GoldenSetInvalido(f"{rotulo} tem 'id' inválido")
    if identificador in ids:
        raise GoldenSetInvalido(f"id duplicado: {identificador}")
    ids.add(identificador)

    categoria = item["categoria"]
    if categoria not in CATEGORIAS:
        raise GoldenSetInvalido(
            f"{identificador}: categoria desconhecida '{categoria}'"
        )
    endpoint = item["endpoint"]
    if endpoint not in ENDERECOS:
        raise GoldenSetInvalido(
            f"{identificador}: endpoint desconhecido '{endpoint}'"
        )
    tipo = item["tipo_resultado"]
    if tipo not in TIPOS_RESULTADO:
        raise GoldenSetInvalido(
            f"{identificador}: tipo_resultado desconhecido '{tipo}'"
        )
    if ENDERECO_POR_TIPO[tipo] != endpoint:
        raise GoldenSetInvalido(
            f"{identificador}: tipo '{tipo}' exige endpoint "
            f"'{ENDERECO_POR_TIPO[tipo]}'"
        )

    pergunta = item["pergunta"]
    if not isinstance(pergunta, str) or not pergunta.strip():
        raise GoldenSetInvalido(f"{identificador}: pergunta vazia")
    if len(pergunta) > MAX_CARACTERES_PERGUNTA:
        raise GoldenSetInvalido(
            f"{identificador}: pergunta acima de {MAX_CARACTERES_PERGUNTA} caracteres"
        )

    tags = item["tags"]
    if not isinstance(tags, list) or not all(isinstance(tag, str) for tag in tags):
        raise GoldenSetInvalido(f"{identificador}: 'tags' deve ser lista de strings")

    esperado = item["esperado"]
    if not isinstance(esperado, dict):
        raise GoldenSetInvalido(f"{identificador}: 'esperado' deve ser objeto")
    _validar_esperado(identificador, esperado)

    if tipo == "assist":
        modo = esperado.get("modo", "summarize")
        if modo not in {"summarize", "explain"}:
            raise GoldenSetInvalido(
                f"{identificador}: modo de assist desconhecido '{modo}'"
            )


def _validar_esperado(identificador: str, esperado: dict[str, Any]) -> None:
    status = esperado.get("status")
    if not isinstance(status, int) or not 100 <= status <= 599:
        raise GoldenSetInvalido(f"{identificador}: 'esperado.status' inválido")

    colunas = esperado.get("colunas_min", [])
    if not isinstance(colunas, list):
        raise GoldenSetInvalido(
            f"{identificador}: 'colunas_min' deve ser lista"
        )
    for entrada in colunas:
        if isinstance(entrada, str):
            if not entrada.strip():
                raise GoldenSetInvalido(
                    f"{identificador}: coluna vazia em 'colunas_min'"
                )
        elif isinstance(entrada, list):
            if not entrada or not all(
                isinstance(alternativa, str) and alternativa.strip()
                for alternativa in entrada
            ):
                raise GoldenSetInvalido(
                    f"{identificador}: alternativa inválida em 'colunas_min'"
                )
        else:
            raise GoldenSetInvalido(
                f"{identificador}: 'colunas_min' aceita string ou lista de strings"
            )

    for campo in ("linhas_min", "fontes_min"):
        valor = esperado.get(campo, 0)
        if not isinstance(valor, int) or isinstance(valor, bool) or valor < 0:
            raise GoldenSetInvalido(f"{identificador}: '{campo}' inválido")


def filtrar_itens(
    itens: Sequence[dict[str, Any]], categorias: set[str] | None
) -> list[dict[str, Any]]:
    """Filtra por categoria preservando a ordem do arquivo."""
    if categorias is None:
        return list(itens)
    return [item for item in itens if item["categoria"] in categorias]


def _parse_categorias(bruto: str | None) -> set[str] | None:
    if not bruto:
        return None
    desejadas = {parte.strip() for parte in bruto.split(",") if parte.strip()}
    desconhecidas = desejadas - CATEGORIAS
    if desconhecidas:
        raise GoldenSetInvalido(
            "categorias desconhecidas: " + ", ".join(sorted(desconhecidas))
        )
    return desejadas


# =====================================================================
# HTTP e coleta
# =====================================================================
def _autenticado(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _resumir_texto(valor: Any, limite: int = 300) -> str:
    texto = " ".join(str(valor).split())
    return texto[:limite] or "sem detalhe"


def _detalhe_resposta(resposta: Resposta) -> str:
    dados = resposta.dados
    if isinstance(dados, dict):
        for campo in ("detail", "message", "error"):
            valor = dados.get(campo)
            if valor:
                return _resumir_texto(valor)
    return _resumir_texto(resposta.texto)


def login(cliente: ClienteHttp, usuario: str, senha: str) -> str:
    """Autentica como admin e devolve o access token; nunca imprime a senha."""
    try:
        resposta = cliente.requisitar(
            "POST",
            "/api/v1/auth/token/",
            corpo={"username": usuario, "password": senha},
        )
    except FalhaRede as exc:
        raise ErroAuth(f"login não respondeu: {exc}") from exc
    if resposta.status != 200:
        raise ErroAuth(
            f"login de {usuario} devolveu HTTP {resposta.status}: "
            f"{_detalhe_resposta(resposta)}"
        )
    token = (resposta.dados or {}).get("access") if isinstance(resposta.dados, dict) else None
    if not isinstance(token, str) or not token:
        raise ErroAuth(f"login de {usuario} não devolveu access token")
    return token


def obter_metricas(cliente: ClienteHttp, token: str) -> dict[str, Any]:
    """Lê `/llm/metrics/`; indisponibilidade não interrompe a avaliação."""
    try:
        resposta = cliente.requisitar(
            "GET", "/api/v1/llm/metrics/", headers=_autenticado(token)
        )
    except FalhaRede:
        return {}
    if resposta.status != 200 or not isinstance(resposta.dados, dict):
        return {}
    return resposta.dados


def resumir_metricas(dados: Mapping[str, Any] | None) -> dict[str, Any]:
    if not dados:
        return {
            "disponivel": False,
            "provedor_configurado": None,
            "provedor_efetivo": None,
            "modelos": {},
            "chamadas": 0,
            "tokens_prompt": 0,
            "tokens_output": 0,
            "custo_usd": 0.0,
            "fallbacks": 0,
            "fallback_ativo": False,
            "ultimo_motivo_fallback": "",
        }
    total = dados.get("total") if isinstance(dados.get("total"), dict) else {}
    return {
        "disponivel": True,
        "provedor_configurado": dados.get("provedor_configurado"),
        "provedor_efetivo": dados.get("provedor_efetivo"),
        "modelos": dados.get("modelos") or {},
        "chamadas": int(total.get("chamadas", 0) or 0),
        "tokens_prompt": int(total.get("tokens_prompt", 0) or 0),
        "tokens_output": int(total.get("tokens_output", 0) or 0),
        "custo_usd": float(total.get("custo_usd", 0.0) or 0.0),
        "fallbacks": int(total.get("fallbacks", 0) or 0),
        "fallback_ativo": bool(dados.get("fallback_ativo")),
        "ultimo_motivo_fallback": str(dados.get("ultimo_motivo_fallback") or ""),
    }


def delta_metricas(
    antes: Mapping[str, Any], depois: Mapping[str, Any]
) -> dict[str, Any]:
    campos = ("chamadas", "tokens_prompt", "tokens_output", "custo_usd", "fallbacks")
    return {
        campo: round(float(depois.get(campo, 0)) - float(antes.get(campo, 0)), 6)
        for campo in campos
    }


# =====================================================================
# Avaliação de um item
# =====================================================================
def _payload(item: Mapping[str, Any]) -> dict[str, Any]:
    endpoint = item["endpoint"]
    if endpoint == ENDERECO_ASSIST:
        esperado = item.get("esperado") or {}
        return {
            "mode": esperado.get("modo", "summarize"),
            "logs": [item["pergunta"]],
            "max_tokens": 128,
        }
    return {"question": item["pergunta"]}


def avaliar_item(
    cliente: ClienteHttp, token: str, item: Mapping[str, Any]
) -> ResultadoItem:
    """Chama o endpoint do item e classifica o desfecho."""
    inicio = time.perf_counter()
    try:
        resposta = cliente.requisitar(
            "POST",
            item["endpoint"],
            corpo=_payload(item),
            headers=_autenticado(token),
        )
        status: int | None = resposta.status
        dados = resposta.dados
        texto = resposta.texto
    except FalhaRede as exc:
        status = None
        dados = None
        texto = str(exc)
    latencia_ms = round((time.perf_counter() - inicio) * 1000.0, 2)

    classificacao = _classificar(item, status, dados, texto)
    return ResultadoItem(
        id=item["id"],
        categoria=item["categoria"],
        endpoint=item["endpoint"],
        tipo_resultado=item["tipo_resultado"],
        pergunta=item["pergunta"],
        status_http=status,
        sucesso=classificacao.sucesso,
        falha=classificacao.falha,
        detalhe=classificacao.detalhe,
        latencia_ms=latencia_ms,
        colunas=classificacao.colunas,
        linhas=classificacao.linhas,
        fontes=classificacao.fontes,
        tokens_prompt=classificacao.tokens_prompt,
        tokens_output=classificacao.tokens_output,
    )


def _classificar(
    item: Mapping[str, Any], status: int | None, dados: Any, texto: str
) -> Classificacao:
    if status is None:
        return Classificacao(
            sucesso=False,
            falha="timeout",
            detalhe=_resumir_texto(texto),
            colunas=[],
        )
    tipo = item["tipo_resultado"]
    esperado = item.get("esperado") or {}
    if tipo == "consulta":
        return _classificar_consulta(status, dados, texto, esperado)
    if tipo == "recusa_esperada":
        return _classificar_recusa(status, dados, texto)
    if tipo == "guardrail_esperado":
        return _classificar_guardrail(status, dados, texto)
    if tipo == "rag_tecnico":
        return _classificar_rag(status, dados, texto, esperado)
    if tipo == "assist":
        return _classificar_assist(status, dados, texto, esperado)
    return Classificacao(
        sucesso=False,
        falha="resposta_inesperada",
        detalhe=f"tipo desconhecido: {tipo}",
        colunas=[],
    )


def _falha_http(
    status: int, dados: Any, texto: str, *, prefixo: str = ""
) -> Classificacao:
    detalhe = _detalhe_resposta(Resposta(status=status, dados=dados, texto=texto))
    if prefixo:
        detalhe = f"{prefixo}: {detalhe}"
    return Classificacao(
        sucesso=False,
        falha=_taxonomia_http(status, dados, texto),
        detalhe=detalhe[:300],
        colunas=[],
    )


def _classificar_consulta(
    status: int, dados: Any, texto: str, esperado: Mapping[str, Any]
) -> Classificacao:
    if status != 200:
        return _falha_http(status, dados, texto, prefixo="esperava 200")
    colunas = _colunas(dados)
    linhas = _linhas(dados)
    faltando = _colunas_faltando(colunas, esperado.get("colunas_min") or [])
    if faltando:
        return Classificacao(
            sucesso=False,
            falha="resposta_inesperada",
            detalhe="colunas ausentes: " + ", ".join(faltando),
            colunas=colunas,
            linhas=linhas,
        )
    minimo = int(esperado.get("linhas_min", 0) or 0)
    if linhas < minimo:
        return Classificacao(
            sucesso=False,
            falha="resposta_inesperada",
            detalhe=f"linhas {linhas} abaixo do mínimo {minimo}",
            colunas=colunas,
            linhas=linhas,
        )
    tokens_prompt, tokens_output = _tokens(dados)
    return Classificacao(
        sucesso=True,
        falha=None,
        detalhe=f"colunas={len(colunas)} linhas={linhas}",
        colunas=colunas,
        linhas=linhas,
        tokens_prompt=tokens_prompt,
        tokens_output=tokens_output,
    )


def _classificar_recusa(
    status: int, dados: Any, texto: str
) -> Classificacao:
    if status == 422:
        return Classificacao(
            sucesso=True,
            falha=None,
            detalhe=_detalhe_resposta(Resposta(status=status, dados=dados, texto=texto)),
            colunas=[],
        )
    return _falha_http(status, dados, texto, prefixo="esperava 422")


def _classificar_guardrail(
    status: int, dados: Any, texto: str
) -> Classificacao:
    if status != 200:
        return _falha_http(status, dados, texto, prefixo="esperava 200")
    fontes = _fontes(dados)
    answer = _answer(dados)
    if fontes != 0:
        return Classificacao(
            sucesso=False,
            falha="resposta_inesperada",
            detalhe=f"guardrail deveria vir sem fontes; vieram {fontes}",
            colunas=[],
            fontes=fontes,
        )
    if _sem_acento(FRASE_GUARDRAIL) not in _sem_acento(answer):
        return Classificacao(
            sucesso=False,
            falha="resposta_vazia" if not answer.strip() else "resposta_inesperada",
            detalhe=_resumir_texto(answer) if answer else "answer vazio",
            colunas=[],
            fontes=fontes,
        )
    return Classificacao(
        sucesso=True,
        falha=None,
        detalhe="guardrail sem fontes",
        colunas=[],
        fontes=0,
    )


def _classificar_rag(
    status: int, dados: Any, texto: str, esperado: Mapping[str, Any]
) -> Classificacao:
    if status != 200:
        return _falha_http(status, dados, texto, prefixo="esperava 200")
    fontes = _fontes(dados)
    minimo = int(esperado.get("fontes_min", 0) or 0)
    answer = _answer(dados)
    if fontes < minimo:
        return Classificacao(
            sucesso=False,
            falha="sem_fonte",
            detalhe=f"fontes {fontes} abaixo do mínimo {minimo}",
            colunas=[],
            fontes=fontes,
        )
    if not answer.strip():
        return Classificacao(
            sucesso=False,
            falha="resposta_vazia",
            detalhe="answer vazio",
            colunas=[],
            fontes=fontes,
        )
    if esperado.get("citacao") and not re.search(r"\[\d+\]", answer):
        return Classificacao(
            sucesso=False,
            falha="sem_citacao",
            detalhe="answer sem citação [n]",
            colunas=[],
            fontes=fontes,
        )
    return Classificacao(
        sucesso=True,
        falha=None,
        detalhe=f"fontes={fontes} citacao={'sim' if re.search(r'\[\d+\]', answer) else 'nao'}",
        colunas=[],
        fontes=fontes,
    )


def _classificar_assist(
    status: int, dados: Any, texto: str, esperado: Mapping[str, Any]
) -> Classificacao:
    if status != 200:
        return _falha_http(status, dados, texto, prefixo="esperava 200")
    answer = _answer(dados)
    minimo = int(esperado.get("resposta_min", 1) or 1)
    if len(answer.strip()) < minimo:
        return Classificacao(
            sucesso=False,
            falha="resposta_vazia",
            detalhe=f"answer com {len(answer.strip())} caracteres",
            colunas=[],
        )
    tokens_prompt, tokens_output = _tokens(dados)
    return Classificacao(
        sucesso=True,
        falha=None,
        detalhe=f"answer={len(answer)} caracteres",
        colunas=[],
        tokens_prompt=tokens_prompt,
        tokens_output=tokens_output,
    )


def _taxonomia_http(status: int, dados: Any, texto: str) -> str:
    if status in {401, 403}:
        return "auth"
    detalhe = _sem_acento(_detalhe_resposta(Resposta(status, dados, texto)))
    if status >= 500:
        if "indice" in detalhe or "indexar_docs" in detalhe:
            return "indice_ausente"
        return "http_5xx"
    if 400 <= status < 500:
        if status == 422:
            if "nao pode ser respondida" in detalhe or "nao contem select" in detalhe:
                return "nao_suportado"
            if "nao pode ser executada" in detalhe or "execucao" in detalhe:
                return "execucao_falhou"
            if any(
                marcador in detalhe
                for marcador in (
                    "fora da allow-list",
                    "palavra proibida",
                    "comando proibido",
                    "select *",
                    "comentario",
                    "funcao proibida",
                )
            ):
                return "sql_proibido"
            return "sql_invalido"
        return "http_4xx_inesperado"
    return "resposta_inesperada"


def _colunas(dados: Any) -> list[str]:
    if isinstance(dados, dict):
        colunas = dados.get("columns")
        if isinstance(colunas, list):
            return [str(coluna) for coluna in colunas]
    return []


def _linhas(dados: Any) -> int:
    if not isinstance(dados, dict):
        return 0
    valor = dados.get("row_count")
    if isinstance(valor, int) and not isinstance(valor, bool):
        return valor
    linhas = dados.get("rows")
    return len(linhas) if isinstance(linhas, list) else 0


def _fontes(dados: Any) -> int:
    if isinstance(dados, dict):
        fontes = dados.get("sources")
        if isinstance(fontes, list):
            return len(fontes)
    return 0


def _answer(dados: Any) -> str:
    if isinstance(dados, dict):
        return str(dados.get("answer") or "")
    return ""


def _tokens(dados: Any) -> tuple[int, int]:
    if not isinstance(dados, dict) or not isinstance(dados.get("meta"), dict):
        return 0, 0
    meta = dados["meta"]
    return (
        int(meta.get("tokens_prompt", 0) or 0),
        int(meta.get("tokens_output", 0) or 0),
    )


def _colunas_faltando(
    colunas: Sequence[str], esperadas: Sequence[Any]
) -> list[str]:
    presentes = {coluna.lower() for coluna in colunas}
    faltando: list[str] = []
    for entrada in esperadas:
        if isinstance(entrada, str):
            if entrada.lower() not in presentes:
                faltando.append(entrada)
            continue
        alternativas = [str(item) for item in entrada]
        if not any(alternativa.lower() in presentes for alternativa in alternativas):
            faltando.append("/".join(alternativas))
    return faltando


def _sem_acento(texto: str) -> str:
    decomposto = unicodedata.normalize("NFKD", texto.lower())
    return "".join(
        caractere for caractere in decomposto if not unicodedata.combining(caractere)
    )


# =====================================================================
# Agregação e relatórios
# =====================================================================
def _percentil(valores: Sequence[float], proporcao: float) -> float:
    if not valores:
        return 0.0
    ordenados = sorted(valores)
    posicao = (len(ordenados) - 1) * proporcao
    inferior = int(posicao)
    superior = min(inferior + 1, len(ordenados) - 1)
    fracao = posicao - inferior
    return round(
        ordenados[inferior] + (ordenados[superior] - ordenados[inferior]) * fracao,
        2,
    )


def agregar(
    resultados: Sequence[ResultadoItem],
    *,
    min_sucesso: float,
    metricas_antes: Mapping[str, Any],
    metricas_depois: Mapping[str, Any],
) -> dict[str, Any]:
    total = len(resultados)
    sucessos = sum(1 for resultado in resultados if resultado.sucesso)
    gate = [
        resultado
        for resultado in resultados
        if resultado.tipo_resultado == "consulta"
        or resultado.categoria == "rag_tecnico"
    ]
    gate_sucessos = sum(1 for resultado in gate if resultado.sucesso)

    por_categoria: dict[str, dict[str, Any]] = {}
    for categoria in ORDEM_CATEGORIAS:
        itens = [resultado for resultado in resultados if resultado.categoria == categoria]
        if not itens:
            continue
        acertos = sum(1 for item in itens if item.sucesso)
        por_categoria[categoria] = {
            "itens": len(itens),
            "sucessos": acertos,
            "taxa": round(acertos / len(itens), 4),
        }
    for categoria in sorted({resultado.categoria for resultado in resultados}):
        if categoria in por_categoria:
            continue
        itens = [resultado for resultado in resultados if resultado.categoria == categoria]
        acertos = sum(1 for item in itens if item.sucesso)
        por_categoria[categoria] = {
            "itens": len(itens),
            "sucessos": acertos,
            "taxa": round(acertos / len(itens), 4),
        }

    falhas = Counter(
        resultado.falha for resultado in resultados if resultado.falha is not None
    )
    latencias = [resultado.latencia_ms for resultado in resultados]
    tokens_prompt = sum(resultado.tokens_prompt for resultado in resultados)
    tokens_output = sum(resultado.tokens_output for resultado in resultados)

    return {
        "total": total,
        "sucessos": sucessos,
        "falhas": total - sucessos,
        "taxa_sucesso": round(sucessos / total, 4) if total else 0.0,
        "gate": {
            "itens": len(gate),
            "sucessos": gate_sucessos,
            "taxa": round(gate_sucessos / len(gate), 4) if gate else 0.0,
            "min_sucesso": min_sucesso,
        },
        "por_categoria": por_categoria,
        "falhas_por_tipo": dict(sorted(falhas.items(), key=lambda item: (-item[1], item[0]))),
        "latencia_ms": {
            "p50": _percentil(latencias, 0.50),
            "p95": _percentil(latencias, 0.95),
            "max": round(max(latencias), 2) if latencias else 0.0,
        },
        "tokens": {
            "prompt": tokens_prompt,
            "output": tokens_output,
            "total": tokens_prompt + tokens_output,
        },
        "metricas_llm": {
            "antes": dict(metricas_antes),
            "depois": dict(metricas_depois),
            "delta": delta_metricas(metricas_antes, metricas_depois),
        },
    }


def _slug_modo(valor: Any) -> str:
    sanitizado = re.sub(r"[^a-z0-9_-]+", "-", str(valor or "").strip().lower())
    return sanitizado.strip("-") or "desconhecido"


def _commit_git() -> str | None:
    try:
        concluido = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    saida = concluido.stdout.strip()
    return saida if concluido.returncode == 0 and saida else None


def _base_relatorio(metadados: Mapping[str, Any]) -> str:
    iniciado = datetime.fromisoformat(str(metadados["iniciado_em"]))
    return f"{iniciado.strftime('%Y-%m-%d_%H%M')}_{metadados['modo']}"


def _caminhos_livres(saida: Path, base: str) -> tuple[Path, Path]:
    sufixo = 0
    while True:
        nome = base if sufixo == 0 else f"{base}_{sufixo + 1}"
        json_path = saida / f"{nome}.json"
        md_path = saida / f"{nome}.md"
        if not json_path.exists() and not md_path.exists():
            return json_path, md_path
        sufixo += 1


def gravar_relatorios(
    *,
    saida: str | Path,
    metadados: Mapping[str, Any],
    resumo: Mapping[str, Any],
    resultados: Sequence[ResultadoItem],
) -> tuple[Path, Path]:
    """Grava o JSON bruto e o resumo Markdown; devolve os caminhos."""
    destino = Path(saida)
    destino.mkdir(parents=True, exist_ok=True)
    json_path, md_path = _caminhos_livres(destino, _base_relatorio(metadados))

    relatorio = {
        "versao_relatorio": 1,
        "metadados": dict(metadados),
        "resumo": dict(resumo),
        "itens": [asdict(resultado) for resultado in resultados],
    }
    json_path.write_text(
        json.dumps(relatorio, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    md_path.write_text(
        _markdown(metadados, resumo, resultados),
        encoding="utf-8",
    )
    return json_path, md_path


def _markdown(
    metadados: Mapping[str, Any],
    resumo: Mapping[str, Any],
    resultados: Sequence[ResultadoItem],
) -> str:
    linhas: list[str] = []
    linhas.append(f"# Avaliação de IA — {metadados['modo']}")
    linhas.append("")
    linhas.append(f"- **Início:** {metadados['iniciado_em']}")
    linhas.append(f"- **Fim:** {metadados['finalizado_em']}")
    linhas.append(f"- **Commit:** `{metadados.get('commit') or 'desconhecido'}`")
    linhas.append(f"- **Base URL:** {metadados['base_url']}")
    linhas.append(
        f"- **Golden set:** versão {metadados['golden_set']['versao']} "
        f"({metadados['golden_set']['itens']} itens)"
    )
    metricas = metadados.get("metricas_llm") or {}
    antes = metricas.get("antes") or {}
    depois = metricas.get("depois") or {}
    linhas.append(
        f"- **Provedor:** configurado={antes.get('provedor_configurado') or '?'} "
        f"efetivo={depois.get('provedor_efetivo') or antes.get('provedor_efetivo') or '?'}"
    )
    linhas.append(f"- **Modelos:** {depois.get('modelos') or antes.get('modelos') or {}}")
    linhas.append("")

    gate = resumo["gate"]
    linhas.append("## Resultado")
    linhas.append("")
    linhas.append(
        f"- **Taxa geral:** {resumo['taxa_sucesso']:.2%} "
        f"({resumo['sucessos']}/{resumo['total']})"
    )
    linhas.append(
        f"- **Gate (`consulta` + `rag_tecnico`):** {gate['taxa']:.2%} "
        f"({gate['sucessos']}/{gate['itens']}) — mínimo {gate['min_sucesso']:.2f}"
    )
    if resumo["falhas"]:
        linhas.append(f"- **Falhas:** {resumo['falhas']}")
    linhas.append("")

    linhas.append("## Taxa por categoria")
    linhas.append("")
    linhas.append("| Categoria | Itens | Sucessos | Taxa |")
    linhas.append("|---|---:|---:|---:|")
    for categoria, dados in resumo["por_categoria"].items():
        linhas.append(
            f"| `{categoria}` | {dados['itens']} | {dados['sucessos']} | "
            f"{dados['taxa']:.2%} |"
        )
    linhas.append("")

    if resumo["falhas_por_tipo"]:
        linhas.append("## Falhas por tipo")
        linhas.append("")
        linhas.append("| Tipo | Ocorrências |")
        linhas.append("|---|---:|")
        for tipo, quantidade in resumo["falhas_por_tipo"].items():
            linhas.append(f"| `{tipo}` | {quantidade} |")
        linhas.append("")

    latencia = resumo["latencia_ms"]
    tokens = resumo["tokens"]
    delta = (resumo.get("metricas_llm") or {}).get("delta") or {}
    depois = (resumo.get("metricas_llm") or {}).get("depois") or {}
    linhas.append("## Latência e consumo")
    linhas.append("")
    linhas.append(f"- **Latência p50:** {latencia['p50']} ms")
    linhas.append(f"- **Latência p95:** {latencia['p95']} ms")
    linhas.append(f"- **Latência máxima:** {latencia['max']} ms")
    linhas.append(f"- **Tokens informados pelas respostas:** {tokens['total']}")
    linhas.append(
        f"- **Snapshot do processo (depois):** chamadas={int(depois.get('chamadas', 0))} "
        f"tokens_prompt={int(depois.get('tokens_prompt', 0))} "
        f"tokens_output={int(depois.get('tokens_output', 0))} "
        f"custo=US$ {float(depois.get('custo_usd', 0.0)):.6f}"
    )
    linhas.append(
        f"- **Fallbacks no snapshot:** {int(depois.get('fallbacks', 0))} "
        f"(ativo={bool(depois.get('fallback_ativo'))})"
    )
    if depois.get("ultimo_motivo_fallback"):
        linhas.append(
            f"- **Último motivo de fallback:** "
            f"`{str(depois['ultimo_motivo_fallback'])[:200]}`"
        )
    linhas.append(
        f"- **Variação observada antes/depois:** "
        f"chamadas={int(delta.get('chamadas', 0))} "
        f"tokens={int(delta.get('tokens_prompt', 0))}+{int(delta.get('tokens_output', 0))} "
        f"fallbacks={int(delta.get('fallbacks', 0))}"
    )
    linhas.append("")

    falhas = [resultado for resultado in resultados if not resultado.sucesso]
    if falhas:
        linhas.append("## Itens com falha")
        linhas.append("")
        linhas.append("| ID | Categoria | HTTP | Falha | Detalhe |")
        linhas.append("|---|---|---:|---|---|")
        for resultado in falhas:
            detalhe = resultado.detalhe.replace("|", "\\|")[:180]
            linhas.append(
                f"| `{resultado.id}` | `{resultado.categoria}` | "
                f"{resultado.status_http if resultado.status_http is not None else '—'} | "
                f"`{resultado.falha}` | {detalhe} |"
            )
        linhas.append("")

    linhas.append("## Limitações")
    linhas.append("")
    linhas.append(
        "- As expectativas são estruturais; o script não julga a exatidão "
        "semântica da resposta, apenas status, colunas, linhas, fontes e citação."
    )
    linhas.append(
        "- O RAG depende do índice gerado por "
        "`python api/manage.py indexar_docs`; índice ausente vira `indice_ausente`."
    )
    linhas.append(
        "- Tokens do `/ask_docs/` não vêm no corpo da resposta; o total do "
        "processo (`/llm/metrics/`) cobre a lacuna quando o endpoint está disponível."
    )
    linhas.append(
        "- As métricas do `/llm/metrics/` são por processo. Com múltiplos "
        "workers do gunicorn, a variação antes/depois pode não representar "
        "exatamente o run; os tokens por item são a fonte mais confiável."
    )
    linhas.append(
        "- O custo é uma estimativa calculada pelas settings `LLM_CUSTO_*`, "
        "inclusive quando o provedor efetivo é o mock."
    )
    linhas.append(
        "- `/assist` é informativo e não entra no gate, conforme a spec 01."
    )
    linhas.append(
        "- Recusas (`fora_dominio`) e guardrails (`rag_fora_corpus`) esperados "
        "contam como comportamento correto."
    )
    linhas.append("")
    return "\n".join(linhas)


def imprimir_resumo(
    resumo: Mapping[str, Any], caminhos: tuple[Path, Path], *, min_sucesso: float
) -> None:
    print("")
    print(
        f"Taxa geral: {resumo['taxa_sucesso']:.2%} "
        f"({resumo['sucessos']}/{resumo['total']})"
    )
    gate = resumo["gate"]
    print(
        f"Gate (consulta + rag_tecnico): {gate['taxa']:.2%} "
        f"({gate['sucessos']}/{gate['itens']}) — mínimo {min_sucesso:.2f}"
    )
    for categoria, dados in resumo["por_categoria"].items():
        print(
            f"  {categoria:<16} {dados['sucessos']}/{dados['itens']} "
            f"({dados['taxa']:.2%})"
        )
    if resumo["falhas_por_tipo"]:
        print("Falhas por tipo:")
        for tipo, quantidade in resumo["falhas_por_tipo"].items():
            print(f"  {tipo}: {quantidade}")
    print(f"Relatório JSON: {caminhos[0]}")
    print(f"Relatório Markdown: {caminhos[1]}")


def _imprimir_golden(dados: Mapping[str, Any]) -> None:
    itens = dados["itens"]
    contagem = Counter(item["categoria"] for item in itens)
    ci_mock = sum(1 for item in itens if "ci_mock" in item["tags"])
    print(
        f"Golden set válido: versão {dados['versao']}, "
        f"{len(itens)} itens, {len(contagem)} categorias, {ci_mock} com ci_mock."
    )
    for categoria in ORDEM_CATEGORIAS:
        if categoria in contagem:
            print(f"  {categoria:<16} {contagem[categoria]}")


# =====================================================================
# Execução
# =====================================================================
def executar(
    *,
    base_url: str = BASE_URL_PADRAO,
    golden_set: str | Path = GOLDEN_SET_PADRAO,
    saida: str | Path = SAIDA_PADRAO,
    usuario: str = "demo_admin",
    senha: str = "",
    timeout: float = TIMEOUT_PADRAO,
    delay: float = DELAY_PADRAO,
    max_questions: int = 0,
    categorias: set[str] | None = None,
    min_sucesso: float = MIN_SUCESSO_PADRAO,
    modo: str | None = None,
    cliente: ClienteHttp | None = None,
) -> int:
    """Executa o golden set e devolve o código de saída."""
    dados = carregar_golden_set(golden_set)
    itens = filtrar_itens(dados["itens"], categorias)
    if max_questions > 0:
        itens = itens[:max_questions]
    if not itens:
        print("Nenhum item após os filtros.", file=sys.stderr)
        return 2

    cliente = cliente or ClienteHttp(base_url, timeout)
    try:
        token = login(cliente, usuario, senha)
    except ErroAuth as exc:
        print(f"Falha de autenticação: {exc}", file=sys.stderr)
        return 3

    iniciado = datetime.now(timezone.utc)
    metricas_antes = resumir_metricas(obter_metricas(cliente, token))
    resultados: list[ResultadoItem] = []

    for numero, item in enumerate(itens, start=1):
        resultado = avaliar_item(cliente, token, item)
        if resultado.status_http == 401:
            try:
                token = login(cliente, usuario, senha)
            except ErroAuth:
                pass
            else:
                print(f"  token renovado; repetindo {item['id']}")
                resultado = avaliar_item(cliente, token, item)
        resultados.append(resultado)
        estado = "OK" if resultado.sucesso else f"FALHA ({resultado.falha})"
        print(
            f"[{numero}/{len(itens)}] {item['categoria']:<16} "
            f"{item['id']:<20} {estado} ({resultado.latencia_ms:.0f} ms)"
        )
        if delay > 0 and numero < len(itens):
            time.sleep(delay)

    finalizado = datetime.now(timezone.utc)
    metricas_depois = obter_metricas(cliente, token)
    if not metricas_depois:
        try:
            token = login(cliente, usuario, senha)
        except ErroAuth:
            pass
        else:
            metricas_depois = obter_metricas(cliente, token)
    metricas_depois = resumir_metricas(metricas_depois)
    resumo = agregar(
        resultados,
        min_sucesso=min_sucesso,
        metricas_antes=metricas_antes,
        metricas_depois=metricas_depois,
    )
    modo_final = (
        modo
        or metricas_depois.get("provedor_configurado")
        or metricas_depois.get("provedor_efetivo")
        or "desconhecido"
    )
    metadados = {
        "iniciado_em": iniciado.isoformat(timespec="seconds"),
        "finalizado_em": finalizado.isoformat(timespec="seconds"),
        "duracao_s": round((finalizado - iniciado).total_seconds(), 2),
        "commit": _commit_git(),
        "base_url": base_url,
        "modo": _slug_modo(modo_final),
        "usuario": usuario,
        "golden_set": {
            "caminho": str(golden_set),
            "versao": dados["versao"],
            "itens": len(itens),
            "categorias": sorted({item["categoria"] for item in itens}),
        },
        "metricas_llm": {
            "antes": metricas_antes,
            "depois": metricas_depois,
        },
    }
    caminhos = gravar_relatorios(
        saida=saida,
        metadados=metadados,
        resumo=resumo,
        resultados=resultados,
    )
    imprimir_resumo(resumo, caminhos, min_sucesso=min_sucesso)
    return 0 if resumo["gate"]["taxa"] >= min_sucesso else 1


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Avalia os pilares de IA do SynapseShop contra um golden set.",
    )
    parser.add_argument(
        "--base-url",
        default=os.environ.get("AVALIACAO_IA_BASE_URL", BASE_URL_PADRAO),
    )
    parser.add_argument(
        "--golden-set",
        default=os.environ.get("AVALIACAO_IA_GOLDEN_SET", str(GOLDEN_SET_PADRAO)),
    )
    parser.add_argument(
        "--saida",
        default=os.environ.get("AVALIACAO_IA_SAIDA", str(SAIDA_PADRAO)),
    )
    parser.add_argument(
        "--usuario",
        default=os.environ.get(
            "AVALIACAO_IA_USUARIO",
            os.environ.get("SEED_ADMIN_USERNAME", "demo_admin"),
        ),
    )
    parser.add_argument(
        "--senha",
        default=None,
        help="Senha do usuário de avaliação (ou AVALIACAO_IA_SENHA/SEED_ADMIN_PASSWORD).",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=float(os.environ.get("AVALIACAO_IA_TIMEOUT", TIMEOUT_PADRAO)),
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=float(os.environ.get("AVALIACAO_IA_DELAY", DELAY_PADRAO)),
        help="Intervalo entre itens, em segundos.",
    )
    parser.add_argument(
        "--max-questions",
        type=int,
        default=0,
        help="Limita a quantidade de itens (0 = todos).",
    )
    parser.add_argument(
        "--categorias",
        default=None,
        help="Lista separada por vírgula (ex.: join,jsonb_itens).",
    )
    parser.add_argument(
        "--min-sucesso",
        type=float,
        default=MIN_SUCESSO_PADRAO,
        help="Taxa mínima do gate para saída 0.",
    )
    parser.add_argument(
        "--modo",
        default=None,
        help="Rótulo do relatório (padrão: provedor efetivo).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Valida o golden set sem fazer chamadas HTTP.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)

    try:
        dados = carregar_golden_set(args.golden_set)
        categorias = _parse_categorias(args.categorias)
    except GoldenSetInvalido as exc:
        print(f"Configuração inválida: {exc}", file=sys.stderr)
        return 2

    if not 0.0 <= args.min_sucesso <= 1.0:
        print("--min-sucesso deve estar entre 0.0 e 1.0", file=sys.stderr)
        return 2
    if args.max_questions < 0:
        print("--max-questions deve ser >= 0", file=sys.stderr)
        return 2
    if args.dry_run:
        _imprimir_golden(dados)
        return 0

    if categorias is not None:
        if not filtrar_itens(dados["itens"], categorias):
            print("Nenhum item nas categorias selecionadas.", file=sys.stderr)
            return 2

    senha = (
        args.senha
        or os.environ.get("AVALIACAO_IA_SENHA")
        or os.environ.get("SEED_ADMIN_PASSWORD")
        or "demo-admin@Synapse2026"
    )
    try:
        return executar(
            base_url=args.base_url,
            golden_set=args.golden_set,
            saida=args.saida,
            usuario=args.usuario,
            senha=senha,
            timeout=args.timeout,
            delay=max(0.0, args.delay),
            max_questions=args.max_questions,
            categorias=categorias,
            min_sucesso=args.min_sucesso,
            modo=args.modo,
        )
    except KeyboardInterrupt:
        print("\nInterrompido pelo usuário.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
