"""Smoke ponta a ponta do MVP SynapseShop (Aula 25).

O script valida a stack **já em execução** e devolve código de saída 0 apenas
quando todos os passos obrigatórios passam. Ele usa somente a biblioteca
padrão: não depende de `requests`, `docker`, Django ou do repositório.

Fluxo coberto:

1. saúde da API e do inventory;
2. login de `demo_admin` e `demo_user`;
3. incremento do cache na listagem do catálogo;
4. criação de pedido com `Idempotency-Key`;
5. repetição do POST e prova de idempotência;
6. pagamento aprovado;
7. espera do worker (pagamento + notificação);
8. `/assist/`;
9. `/ask_sql/`;
10. `/ask_docs/` com pelo menos uma fonte;
11. mock de front-end em `/app/`;
12. saúde do dashboard Streamlit.

Uso:

    python scripts/validar_mvp.py
    python scripts/validar_mvp.py --base-url http://localhost:8000 --skip-ai
    python scripts/validar_mvp.py --inventory-url http://localhost:8001 --timeout 30

As credenciais demo são lidas de `SEED_ADMIN_*`/`SEED_USER_*` (mesmas do
`seed_auth`) e nunca são impressas. A saída termina com um JSON com `ok`,
`passos`, `skipped` e `falhas`.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

API_PADRAO = "http://localhost:8000"
INVENTORY_PADRAO = "http://localhost:8001"
DASHBOARD_PADRAO = "http://localhost:8501"
TIMEOUT_PADRAO = 30.0
INTERVALO_POLLING = 1.0

PASSOS_IA = frozenset({"/assist/", "/ask_sql/", "/ask_docs/"})


class ErroValidacao(RuntimeError):
    """Um passo obrigatório não produziu o resultado esperado."""


class PassoPulado(RuntimeError):
    """O passo não se aplica ao ambiente atual (ex.: cache desabilitado)."""


@dataclass
class Resposta:
    status: int
    dados: Any
    texto: str


class ClienteHttp:
    """Cliente HTTP mínimo com timeout e leitura de corpo em erros."""

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
        esperado: Sequence[int] = (200,),
    ) -> Resposta:
        url = caminho if caminho.startswith("http") else self.base_url + "/" + caminho.lstrip("/")
        dados = None
        cabecalhos = {"Accept": "application/json", **(headers or {})}
        if corpo is not None:
            dados = json.dumps(corpo).encode("utf-8")
            cabecalhos.setdefault("Content-Type", "application/json")
        requisicao = urllib.request.Request(
            url,
            data=dados,
            headers=cabecalhos,
            method=metodo.upper(),
        )
        try:
            with urllib.request.urlopen(requisicao, timeout=self.timeout) as resposta:
                status = int(resposta.status)
                texto = resposta.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            status = int(exc.code)
            texto = exc.read().decode("utf-8", errors="replace")
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise ErroValidacao(
                f"{metodo.upper()} {url} falhou antes da resposta: {exc}"
            ) from exc

        try:
            corpo_json = json.loads(texto) if texto else None
        except ValueError:
            corpo_json = None

        if status not in esperado:
            resumo = " ".join(texto.split())[:300] or "sem corpo"
            raise ErroValidacao(
                f"{metodo.upper()} {caminho} devolveu HTTP {status}: {resumo}"
            )
        return Resposta(status=status, dados=corpo_json, texto=texto)


def _credenciais() -> tuple[tuple[str, str], tuple[str, str]]:
    admin = (
        os.environ.get("SEED_ADMIN_USERNAME", "demo_admin"),
        os.environ.get("SEED_ADMIN_PASSWORD", "demo-admin@Synapse2026"),
    )
    usuario = (
        os.environ.get("SEED_USER_USERNAME", "demo_user"),
        os.environ.get("SEED_USER_PASSWORD", "demo-user@Synapse2026"),
    )
    return admin, usuario


def _login(cliente: ClienteHttp, usuario: str, senha: str) -> str:
    resposta = cliente.requisitar(
        "POST",
        "/api/v1/auth/token/",
        corpo={"username": usuario, "password": senha},
        esperado=(200,),
    )
    dados = resposta.dados or {}
    token = dados.get("access")
    if not isinstance(token, str) or not token:
        raise ErroValidacao(f"login de {usuario} não devolveu access token")
    return token


def _autenticado(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _health(contexto: dict[str, Any]) -> str:
    resposta = contexto["api"].requisitar("GET", "/health", esperado=(200,))
    dados = resposta.dados or {}
    if dados.get("status") != "ok":
        raise ErroValidacao(f"API /health inesperado: {dados!r}")
    if dados.get("service") != "synapseshop-api":
        raise ErroValidacao(f"serviço inesperado em /health: {dados.get('service')!r}")

    inventario = contexto["inventory"].requisitar("GET", "/health", esperado=(200,))
    dados_inventario = inventario.dados or {}
    if dados_inventario.get("status") != "ok":
        raise ErroValidacao(f"inventory /health inesperado: {dados_inventario!r}")
    servico_inventario = dados_inventario.get("service", "synapseshop-inventory")
    return f"api={dados['service']} inventory={servico_inventario}"


def _login_demos(contexto: dict[str, Any]) -> str:
    (admin_usuario, admin_senha), (usuario, senha) = _credenciais()
    contexto["admin_token"] = _login(contexto["api"], admin_usuario, admin_senha)
    contexto["user_token"] = _login(contexto["api"], usuario, senha)
    return f"{admin_usuario} + {usuario}"


def _cache(contexto: dict[str, Any]) -> str:
    api: ClienteHttp = contexto["api"]
    headers = _autenticado(contexto["admin_token"])
    antes = api.requisitar(
        "GET", "/api/v1/cache/metrics/", headers=headers, esperado=(200,)
    )
    dados_antes = antes.dados or {}
    if not dados_antes.get("cache_habilitado"):
        raise PassoPulado("cache desabilitado no ambiente")
    lookups_antes = int((dados_antes.get("total") or {}).get("lookups", 0))

    api.requisitar("GET", "/api/v1/items/", esperado=(200,))
    api.requisitar("GET", "/api/v1/items/", esperado=(200,))

    depois = api.requisitar(
        "GET", "/api/v1/cache/metrics/", headers=headers, esperado=(200,)
    )
    dados_depois = depois.dados or {}
    lookups_depois = int((dados_depois.get("total") or {}).get("lookups", 0))
    if lookups_depois <= lookups_antes:
        raise ErroValidacao(
            "cache habilitado, mas os lookups não aumentaram "
            f"({lookups_antes} -> {lookups_depois})"
        )
    return f"lookups {lookups_antes} -> {lookups_depois}"


def _criar_pedido(contexto: dict[str, Any]) -> str:
    api: ClienteHttp = contexto["api"]
    catalogo = api.requisitar(
        "GET", "/api/v1/items/?is_active=true", esperado=(200,)
    )
    produtos = (catalogo.dados or {}).get("results") or []
    if not produtos:
        raise ErroValidacao(
            "catálogo vazio; execute `python api/manage.py seed_demo` antes do smoke"
        )
    sku = str(produtos[0]["sku"])
    chave = f"mvp-smoke-{uuid.uuid4().hex}"
    corpo = {"itens": [{"sku": sku, "quantidade": 1}]}
    resposta = api.requisitar(
        "POST",
        "/api/v1/pedidos/",
        corpo=corpo,
        headers={**_autenticado(contexto["user_token"]), "Idempotency-Key": chave},
        esperado=(201,),
    )
    dados = resposta.dados or {}
    if not dados.get("id"):
        raise ErroValidacao("POST /pedidos/ não devolveu id")
    contexto.update(
        {
            "pedido_id": int(dados["id"]),
            "pedido_corpo": corpo,
            "pedido_chave": chave,
        }
    )
    return f"pedido={dados['id']} sku={sku}"


def _idempotencia(contexto: dict[str, Any]) -> str:
    api: ClienteHttp = contexto["api"]
    resposta = api.requisitar(
        "POST",
        "/api/v1/pedidos/",
        corpo=contexto["pedido_corpo"],
        headers={
            **_autenticado(contexto["user_token"]),
            "Idempotency-Key": contexto["pedido_chave"],
        },
        esperado=(200,),
    )
    dados = resposta.dados or {}
    if int(dados.get("id", 0)) != contexto["pedido_id"]:
        raise ErroValidacao(
            "re-POST devolveu outro pedido: "
            f"{dados.get('id')!r} != {contexto['pedido_id']!r}"
        )
    if not (dados.get("evento") or {}).get("duplicado"):
        raise ErroValidacao("re-POST não sinalizou evento duplicado")
    return f"mesmo id={contexto['pedido_id']} com 200"


def _pagamento(contexto: dict[str, Any]) -> str:
    resposta = contexto["api"].requisitar(
        "POST",
        f"/api/v1/pedidos/{contexto['pedido_id']}/pagamento/",
        corpo={"metodo": "pix", "aprovado": True, "canal": "email"},
        headers=_autenticado(contexto["user_token"]),
        esperado=(201,),
    )
    dados = resposta.dados or {}
    if not dados.get("transacao_id"):
        raise ErroValidacao("pagamento sem transacao_id")
    return f"pagamento={dados.get('id', '?')} status={dados.get('status', '?')}"


def _aguardar_worker(contexto: dict[str, Any]) -> str:
    api: ClienteHttp = contexto["api"]
    headers = _autenticado(contexto["user_token"])
    prazo = time.monotonic() + float(contexto["timeout"])
    status_pagamento = None
    notificacoes: list[Any] = []

    while time.monotonic() < prazo:
        pagamento = api.requisitar(
            "GET",
            f"/api/v1/pedidos/{contexto['pedido_id']}/pagamento/",
            headers=headers,
            esperado=(200, 404),
        )
        if pagamento.status == 200:
            status_pagamento = (pagamento.dados or {}).get("status")
        if status_pagamento in {"aprovado", "recusado"}:
            lista = api.requisitar(
                "GET",
                f"/api/v1/notificacoes/?pedido={contexto['pedido_id']}",
                headers=headers,
                esperado=(200,),
            )
            notificacoes = (lista.dados or {}).get("results") or []
            if notificacoes:
                break
        time.sleep(INTERVALO_POLLING)

    if status_pagamento not in {"aprovado", "recusado"}:
        raise ErroValidacao(
            "o worker não concluiu o pagamento dentro do timeout "
            f"({contexto['timeout']} s); verifique os logs de worker-kafka"
        )
    if not notificacoes:
        raise ErroValidacao(
            "pagamento concluído, mas nenhuma notificação apareceu dentro do timeout"
        )
    return f"pagamento={status_pagamento} notificacoes={len(notificacoes)}"


def _assist(contexto: dict[str, Any]) -> str:
    resposta = contexto["api"].requisitar(
        "POST",
        "/api/v1/assist/",
        corpo={
            "mode": "summarize",
            "logs": "2026-11-08 10:00 ERROR timeout ao conectar no banco",
            "max_tokens": 128,
        },
        headers=_autenticado(contexto["admin_token"]),
        esperado=(200,),
    )
    answer = str((resposta.dados or {}).get("answer") or "").strip()
    if not answer:
        raise ErroValidacao("/assist/ devolveu answer vazio")
    return f"answer={len(answer)} caracteres"


def _ask_sql(contexto: dict[str, Any]) -> str:
    resposta = contexto["api"].requisitar(
        "POST",
        "/api/v1/ask_sql/",
        corpo={"question": "Quantos pedidos existem por status?"},
        headers=_autenticado(contexto["admin_token"]),
        esperado=(200,),
    )
    dados = resposta.dados or {}
    if not dados.get("sql"):
        raise ErroValidacao("/ask_sql/ não devolveu SQL")
    if not isinstance(dados.get("columns"), list):
        raise ErroValidacao("/ask_sql/ não devolveu colunas")
    return f"rows={dados.get('row_count', 0)} modelo={(dados.get('meta') or {}).get('modelo', '?')}"


def _ask_docs(contexto: dict[str, Any]) -> str:
    resposta = contexto["api"].requisitar(
        "POST",
        "/api/v1/ask_docs/",
        corpo={"question": "Como rodar os testes?", "top_k": 3, "min_score": 0.25},
        headers=_autenticado(contexto["admin_token"]),
        esperado=(200,),
    )
    dados = resposta.dados or {}
    fontes = dados.get("sources") or []
    if not fontes:
        raise ErroValidacao(
            "/ask_docs/ não citou fontes; execute "
            "`python api/manage.py indexar_docs` e confira o limiar de score"
        )
    return f"sources={len(fontes)}"


def _app_frontend(contexto: dict[str, Any]) -> str:
    resposta = contexto["api"].requisitar("GET", "/app/", esperado=(200,))
    if "SynapseShop" not in resposta.texto:
        raise ErroValidacao("/app/ não devolveu o mock de front-end")
    return "mock same-origin"


def _health_dashboard(contexto: dict[str, Any]) -> str:
    resposta = contexto["dashboard"].requisitar(
        "GET", "/_stcore/health", esperado=(200,)
    )
    if resposta.texto.strip().lower() != "ok":
        raise ErroValidacao(f"dashboard health inesperado: {resposta.texto[:120]!r}")
    return "ok"


def _passos() -> list[tuple[str, Callable[[dict[str, Any]], str]]]:
    return [
        ("Saúde da API + inventory", _health),
        ("Login demo_admin + demo_user", _login_demos),
        ("Cache do catálogo", _cache),
        ("Criação de pedido", _criar_pedido),
        ("Idempotência do pedido", _idempotencia),
        ("Pagamento aprovado", _pagamento),
        ("Worker: pagamento + notificação", _aguardar_worker),
        ("IA: /assist/", _assist),
        ("IA: /ask_sql/", _ask_sql),
        ("IA: /ask_docs/", _ask_docs),
        ("Front-end /app/", _app_frontend),
        ("Saúde do dashboard", _health_dashboard),
    ]


def _pular_ia(nome: str) -> bool:
    return any(marcador in nome for marcador in PASSOS_IA)


def executar(
    *,
    base_url: str = API_PADRAO,
    inventory_url: str = INVENTORY_PADRAO,
    dashboard_url: str = DASHBOARD_PADRAO,
    timeout: float = TIMEOUT_PADRAO,
    skip_ai: bool = False,
    clientes: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Executa a sequência e devolve o resumo estruturado (sem `sys.exit`)."""
    contexto: dict[str, Any] = {
        "api": ClienteHttp(base_url, timeout),
        "inventory": ClienteHttp(inventory_url, timeout),
        "dashboard": ClienteHttp(dashboard_url, timeout),
        "timeout": timeout,
    }
    if clientes:
        contexto.update(clientes)

    passos: list[dict[str, Any]] = []
    skipped: list[str] = []
    falhas: list[str] = []
    total = len(_passos())

    for numero, (nome, funcao) in enumerate(_passos(), start=1):
        if skip_ai and _pular_ia(nome):
            print(f"[{numero}/{total}] {nome} ... SKIP")
            skipped.append(nome)
            continue
        print(f"[{numero}/{total}] {nome} ... ", end="", flush=True)
        try:
            detalhe = funcao(contexto)
        except PassoPulado as exc:
            print(f"SKIP ({exc})")
            skipped.append(nome)
            continue
        except ErroValidacao as exc:
            print("FALHA")
            falhas.append(f"{nome}: {exc}")
            break
        print(f"OK ({detalhe})")
        passos.append({"numero": numero, "nome": nome, "status": "PASS", "detalhe": detalhe})

    resultado = {
        "ok": not falhas,
        "passos": passos,
        "skipped": skipped,
        "falhas": falhas,
    }
    return resultado


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Valida o fluxo ponta a ponta do MVP SynapseShop.",
    )
    parser.add_argument("--base-url", default=os.environ.get("MVP_API_URL", API_PADRAO))
    parser.add_argument(
        "--inventory-url",
        default=os.environ.get("MVP_INVENTORY_URL", INVENTORY_PADRAO),
    )
    parser.add_argument(
        "--dashboard-url",
        default=os.environ.get("MVP_DASHBOARD_URL", DASHBOARD_PADRAO),
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=float(os.environ.get("MVP_TIMEOUT", TIMEOUT_PADRAO)),
        help="Timeout HTTP e prazo de espera do worker, em segundos.",
    )
    parser.add_argument(
        "--skip-ai",
        action="store_true",
        help="Pula /assist/, /ask_sql/ e /ask_docs/ (marcados como SKIP).",
    )
    args = parser.parse_args(argv)

    try:
        resultado = executar(
            base_url=args.base_url,
            inventory_url=args.inventory_url,
            dashboard_url=args.dashboard_url,
            timeout=args.timeout,
            skip_ai=args.skip_ai,
        )
    except KeyboardInterrupt:
        print("\nInterrompido pelo usuário.", file=sys.stderr)
        return 130

    print("\nResumo:", "OK" if resultado["ok"] else "FALHA")
    if resultado["falhas"]:
        for falha in resultado["falhas"]:
            print(f"  - {falha}", file=sys.stderr)
    print(json.dumps(resultado, ensure_ascii=False, indent=2))
    return 0 if resultado["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
