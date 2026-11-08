"""Testes do smoke ponta a ponta `scripts/validar_mvp.py` (Aula 25).

O script é exercitado com clientes HTTP falsos: nenhum teste abre socket,
toca o banco ou depende da stack no ar.
"""

from __future__ import annotations

import json

import pytest

from scripts import validar_mvp

pytestmark = pytest.mark.unit


def _resposta(status: int, dados=None, texto: str = "") -> validar_mvp.Resposta:
    if not texto:
        texto = json.dumps(dados) if dados is not None else ""
    return validar_mvp.Resposta(status=status, dados=dados, texto=texto)


class ApiFalsa:
    def __init__(self) -> None:
        self.chamadas: list[tuple[str, str]] = []
        self._metricas = 0
        self._pedidos_postados = 0

    def requisitar(self, metodo, caminho, *, corpo=None, headers=None, esperado=(200,)):
        self.chamadas.append((metodo, caminho))
        base = caminho.split("?", 1)[0]

        if base == "/health":
            return _resposta(200, {"status": "ok", "service": "synapseshop-api"})
        if base == "/api/v1/auth/token/":
            return _resposta(200, {"access": "token-de-teste", "refresh": "refresh"})
        if base == "/api/v1/cache/metrics/":
            self._metricas += 1
            lookups = 0 if self._metricas == 1 else 2
            return _resposta(200, {"cache_habilitado": True, "total": {"lookups": lookups}})
        if base == "/api/v1/items/":
            return _resposta(200, {"results": [{"sku": "AAA-1"}]})
        if base == "/api/v1/pedidos/":
            self._pedidos_postados += 1
            if self._pedidos_postados == 1:
                return _resposta(201, {"id": 1, "status": "pendente"})
            return _resposta(
                200,
                {"id": 1, "status": "pendente", "evento": {"duplicado": True}},
            )
        if base == "/api/v1/pedidos/1/pagamento/":
            if metodo == "POST":
                return _resposta(
                    201,
                    {"id": 1, "transacao_id": "txn-1", "status": "registrado"},
                )
            return _resposta(200, {"id": 1, "status": "aprovado"})
        if base == "/api/v1/notificacoes/":
            return _resposta(200, {"results": [{"id": 1, "titulo": "Pagamento aprovado"}]})
        if base == "/api/v1/assist/":
            return _resposta(200, {"answer": "Resumo do log", "meta": {}})
        if base == "/api/v1/ask_sql/":
            return _resposta(
                200,
                {
                    "sql": "SELECT status FROM core_pedido",
                    "columns": ["status"],
                    "rows": [["pendente"]],
                    "row_count": 1,
                    "meta": {"modelo": "mock-sql"},
                },
            )
        if base == "/api/v1/ask_docs/":
            return _resposta(200, {"answer": "Resposta [1]", "sources": [{"path": "README.md"}]})
        if base == "/app/":
            return _resposta(200, None, "<!DOCTYPE html><html><h1>SynapseShop</h1></html>")
        raise AssertionError(f"chamada inesperada: {metodo} {caminho}")


class ClienteHealthFalso:
    def __init__(self, servico: str, texto: str = "") -> None:
        self.servico = servico
        self.texto = texto

    def requisitar(self, metodo, caminho, **_kwargs):
        if self.texto:
            return _resposta(200, None, self.texto)
        return _resposta(200, {"status": "ok", "service": self.servico})


def _executar(**kwargs):
    return validar_mvp.executar(
        clientes={
            "api": ApiFalsa(),
            "inventory": ClienteHealthFalso("synapseshop-inventory"),
            "dashboard": ClienteHealthFalso("", texto="ok"),
        },
        **kwargs,
    )


def test_smoke_completo_termina_ok_com_doze_passos():
    resumo = _executar(timeout=1.0)

    assert resumo["ok"] is True
    assert resumo["falhas"] == []
    assert resumo["skipped"] == []
    assert len(resumo["passos"]) == 12
    assert [passo["numero"] for passo in resumo["passos"]] == list(range(1, 13))


def test_skip_ai_marca_tres_passos_sem_chamar_os_endpoints():
    api = ApiFalsa()
    resumo = validar_mvp.executar(
        timeout=1.0,
        skip_ai=True,
        clientes={
            "api": api,
            "inventory": ClienteHealthFalso("synapseshop-inventory"),
            "dashboard": ClienteHealthFalso("", texto="ok"),
        },
    )

    assert resumo["ok"] is True
    assert resumo["skipped"] == ["IA: /assist/", "IA: /ask_sql/", "IA: /ask_docs/"]
    assert len(resumo["passos"]) == 9
    caminhos = {caminho for _, caminho in api.chamadas}
    assert "/api/v1/assist/" not in caminhos
    assert "/api/v1/ask_sql/" not in caminhos
    assert "/api/v1/ask_docs/" not in caminhos


def test_falha_em_passo_obrigatorio_interrompe_e_reprova():
    class ApiSaudeRuim(ApiFalsa):
        def requisitar(self, metodo, caminho, **kwargs):
            if caminho == "/health":
                self.chamadas.append((metodo, caminho))
                return _resposta(200, {"status": "down", "service": "synapseshop-api"})
            return super().requisitar(metodo, caminho, **kwargs)

    resumo = validar_mvp.executar(
        timeout=1.0,
        clientes={
            "api": ApiSaudeRuim(),
            "inventory": ClienteHealthFalso("synapseshop-inventory"),
            "dashboard": ClienteHealthFalso("", texto="ok"),
        },
    )

    assert resumo["ok"] is False
    assert resumo["passos"] == []
    assert len(resumo["falhas"]) == 1
    assert "Saúde da API" in resumo["falhas"][0]


def test_main_devolve_um_quando_ha_falha(monkeypatch, capsys):
    monkeypatch.setattr(
        validar_mvp,
        "executar",
        lambda **kwargs: {"ok": False, "passos": [], "skipped": [], "falhas": ["falhou"]},
    )

    assert validar_mvp.main([]) == 1
    assert "FALHA" in capsys.readouterr().out


def test_main_devolve_zero_quando_tudo_passa(monkeypatch):
    monkeypatch.setattr(
        validar_mvp,
        "executar",
        lambda **kwargs: {"ok": True, "passos": [], "skipped": [], "falhas": []},
    )

    assert validar_mvp.main(["--skip-ai"]) == 0
