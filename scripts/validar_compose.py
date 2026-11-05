"""Smoke test de integração dos serviços do Docker Compose (Aula 23).

O job `compose-smoke` do GitHub Actions sobe `db`, `api` e `dashboard` com
`docker compose up --wait` e então executa este script. As verificações
provam os caminhos que um healthcheck isolado não prova:

1. host -> API (`GET /health`);
2. host -> dashboard (`GET /_stcore/health`);
3. API -> PostgreSQL (`manage.py migrate --check`);
4. dashboard -> PostgreSQL (`dashboard.queries.contar_pedidos`);
5. dashboard -> API (chamada HTTP de dentro do container do painel).

Uso local (o stack já precisa estar no ar):

    docker compose up -d --wait db api dashboard
    python scripts/validar_compose.py

Somente a biblioteca padrão é usada: o script roda no runner e no Windows,
e as credenciais ficam nos containers — nenhum valor sensível é impresso.
"""

from __future__ import annotations

import argparse
import json
import os  # falha proposital do drill de CI (será revertida)
import subprocess
import sys
import time
import urllib.request
from collections.abc import Callable, Sequence
from typing import Any

API_PADRAO = "http://localhost:8000"
DASHBOARD_PADRAO = "http://localhost:8501"
TENTATIVAS = 30
INTERVALO_SEGUNDOS = 2.0


class FalhaValidacao(RuntimeError):
    """Uma verificação do smoke test não produziu o resultado esperado."""


def _requisitar(url: str, timeout: float = 10.0) -> tuple[int, bytes]:
    with urllib.request.urlopen(url, timeout=timeout) as resposta:
        return int(resposta.status), resposta.read()


def _aguardar_json(url: str, campo: str, valor: str) -> dict[str, Any]:
    ultimo_erro: Exception | None = None
    for tentativa in range(1, TENTATIVAS + 1):
        try:
            status, corpo = _requisitar(url)
            dados = json.loads(corpo)
            if status == 200 and isinstance(dados, dict) and dados.get(campo) == valor:
                return dados
            ultimo_erro = FalhaValidacao(
                f"resposta inesperada (status={status}): {corpo[:200]!r}"
            )
        except (OSError, ValueError) as exc:
            ultimo_erro = exc
        if tentativa < TENTATIVAS:
            time.sleep(INTERVALO_SEGUNDOS)
    raise FalhaValidacao(
        f"{url} não respondeu como esperado após {TENTATIVAS} tentativas: {ultimo_erro}"
    )


def _aguardar_texto(url: str, esperado: str) -> str:
    ultimo_erro: Exception | None = None
    for tentativa in range(1, TENTATIVAS + 1):
        try:
            status, corpo = _requisitar(url)
            texto = corpo.decode("utf-8", errors="replace").strip()
            if status == 200 and texto == esperado:
                return texto
            ultimo_erro = FalhaValidacao(
                f"resposta inesperada (status={status}): {texto[:200]!r}"
            )
        except (OSError, ValueError) as exc:
            ultimo_erro = exc
        if tentativa < TENTATIVAS:
            time.sleep(INTERVALO_SEGUNDOS)
    raise FalhaValidacao(
        f"{url} não respondeu como esperado após {TENTATIVAS} tentativas: {ultimo_erro}"
    )


def _compose(*argumentos: str, timeout: float = 120.0) -> str:
    comando = ["docker", "compose", *argumentos]
    try:
        resultado = subprocess.run(
            comando,
            check=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        raise FalhaValidacao("docker não encontrado no PATH") from exc
    except subprocess.CalledProcessError as exc:
        detalhe = (exc.stderr or exc.stdout or "").strip()
        raise FalhaValidacao(
            f"comando falhou: {' '.join(comando)}\n{detalhe}"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise FalhaValidacao(f"timeout em: {' '.join(comando)}") from exc
    return resultado.stdout.strip()


def _validar_host_api(api_url: str) -> str:
    dados = _aguardar_json(f"{api_url.rstrip('/')}/health", "status", "ok")
    servico = str(dados.get("service", ""))
    if servico != "synapseshop-api":
        raise FalhaValidacao(f"serviço inesperado em /health: {servico!r}")
    return f"service={servico}"


def _validar_host_dashboard(dashboard_url: str) -> str:
    return _aguardar_texto(
        f"{dashboard_url.rstrip('/')}/_stcore/health",
        "ok",
    )


def _validar_api_postgres() -> str:
    # `migrate --check` falha com exit != 0 se houver migração pendente e,
    # para decidir isso, abre conexão real com o PostgreSQL do Compose.
    _compose("exec", "-T", "api", "python", "api/manage.py", "migrate", "--check")
    return "migrações aplicadas"


def _validar_dashboard_postgres() -> str:
    codigo = (
        "from dashboard.queries import contar_pedidos; "
        "print(f'pedidos={contar_pedidos()}')"
    )
    saida = _compose("exec", "-T", "dashboard", "python", "-c", codigo)
    if not saida.startswith("pedidos="):
        raise FalhaValidacao(f"saída inesperada do dashboard: {saida!r}")
    return saida


def _validar_dashboard_api() -> str:
    codigo = (
        "import json, urllib.request; "
        "dados = json.loads("
        "urllib.request.urlopen('http://api:8000/health', timeout=10).read()"
        "); "
        "print(dados['service'])"
    )
    # `http://api:8000` só resolve dentro da rede do Compose: isto prova que
    # o painel alcança a API pelo nome do serviço, não pelo localhost do host.
    saida = _compose("exec", "-T", "dashboard", "python", "-c", codigo)
    if saida != "synapseshop-api":
        raise FalhaValidacao(f"dashboard não alcançou a API: {saida!r}")
    return saida


def _diagnosticos() -> None:
    print("\n--- docker compose ps ---", file=sys.stderr)
    subprocess.run(["docker", "compose", "ps"], check=False)
    print("\n--- últimos logs (db, api, dashboard) ---", file=sys.stderr)
    subprocess.run(
        [
            "docker",
            "compose",
            "logs",
            "--no-color",
            "--tail=120",
            "db",
            "api",
            "dashboard",
        ],
        check=False,
    )


def _executar_verificacao(
    numero: int,
    total: int,
    nome: str,
    funcao: Callable[[], str],
) -> None:
    print(f"[{numero}/{total}] {nome} ... ", end="", flush=True)
    detalhe = funcao()
    sufixo = f" ({detalhe})" if detalhe else ""
    print(f"OK{sufixo}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Valida a comunicação entre os serviços do Compose.",
    )
    parser.add_argument("--api-url", default=API_PADRAO)
    parser.add_argument("--dashboard-url", default=DASHBOARD_PADRAO)
    args = parser.parse_args(argv)

    verificacoes: list[tuple[str, Callable[[], str]]] = [
        ("host -> API (GET /health)", lambda: _validar_host_api(args.api_url)),
        (
            "host -> dashboard (GET /_stcore/health)",
            lambda: _validar_host_dashboard(args.dashboard_url),
        ),
        ("API -> PostgreSQL", _validar_api_postgres),
        ("dashboard -> PostgreSQL", _validar_dashboard_postgres),
        ("dashboard -> API", _validar_dashboard_api),
    ]

    try:
        for numero, (nome, funcao) in enumerate(verificacoes, start=1):
            _executar_verificacao(numero, len(verificacoes), nome, funcao)
    except FalhaValidacao as exc:
        print(f"\nFALHA: {exc}", file=sys.stderr)
        _diagnosticos()
        return 1

    print(
        f"\nSmoke do Compose concluído: "
        f"{len(verificacoes)}/{len(verificacoes)} verificações."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
