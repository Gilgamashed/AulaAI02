"""Cliente HTTP do painel de consulta em linguagem natural (Aula 21)."""

from __future__ import annotations

import io
import json
from urllib import error

import pytest

from dashboard import ask_sql as ask_sql_mod
from dashboard.ask_sql import AskSqlErro, api_base_url, login, perguntar

pytestmark = pytest.mark.unit


class _RespostaFake:
    def __init__(self, payload: dict | None = None, texto: str | None = None) -> None:
        if texto is not None:
            self._corpo = texto.encode("utf-8")
        else:
            self._corpo = json.dumps(payload or {}).encode("utf-8")

    def read(self) -> bytes:
        return self._corpo

    def __enter__(self) -> "_RespostaFake":
        return self

    def __exit__(self, *args) -> bool:
        return False


def _urlopen_fake(monkeypatch, *, resposta=None, erro=None, texto=None):
    chamadas: list[dict] = []

    def fake(requisicao, timeout):
        chamadas.append(
            {
                "url": requisicao.full_url,
                "metodo": requisicao.get_method(),
                "corpo": json.loads(requisicao.data.decode("utf-8"))
                if requisicao.data
                else None,
                "cabecalhos": dict(requisicao.header_items()),
                "timeout": timeout,
            }
        )
        if erro is not None:
            raise erro
        return _RespostaFake(resposta, texto)

    monkeypatch.setattr(ask_sql_mod.request, "urlopen", fake)
    return chamadas


def _http_error(status: int, corpo: str) -> error.HTTPError:
    return error.HTTPError(
        "http://localhost:8000/api/v1/ask_sql/",
        status,
        "erro",
        None,
        io.BytesIO(corpo.encode("utf-8")),
    )


def test_api_base_url_prioriza_dashboard_api_url(monkeypatch):
    monkeypatch.setenv("DASHBOARD_API_URL", "http://api:8000/")
    monkeypatch.setenv("API_BASE_URL", "http://localhost:9000")

    assert api_base_url() == "http://api:8000"


def test_api_base_url_usa_api_base_url_como_fallback(monkeypatch):
    monkeypatch.delenv("DASHBOARD_API_URL", raising=False)
    monkeypatch.setenv("API_BASE_URL", "http://localhost:9000/")

    assert api_base_url() == "http://localhost:9000"


def test_login_envia_credenciais_e_devolve_access(monkeypatch):
    chamadas = _urlopen_fake(monkeypatch, resposta={"access": "jwt-123"})

    token = login("demo_admin", "senha", timeout=3.0)

    assert token == "jwt-123"
    assert chamadas[0]["url"] == "http://localhost:8000/api/v1/auth/token/"
    assert chamadas[0]["metodo"] == "POST"
    assert chamadas[0]["corpo"] == {"username": "demo_admin", "password": "senha"}
    assert chamadas[0]["timeout"] == 3.0


def test_login_sem_access_falha(monkeypatch):
    _urlopen_fake(monkeypatch, resposta={"refresh": "x"})

    with pytest.raises(AskSqlErro):
        login("demo_admin", "senha")


def test_login_401_traduz_erro(monkeypatch):
    _urlopen_fake(monkeypatch, erro=_http_error(401, '{"detail": "credenciais"}'))

    with pytest.raises(AskSqlErro) as excinfo:
        login("demo_admin", "errada")

    assert excinfo.value.status == 401
    assert "credenciais" in str(excinfo.value)


def test_perguntar_envia_token_e_normaliza_resposta(monkeypatch):
    chamadas = _urlopen_fake(
        monkeypatch,
        resposta={
            "question": "Quantos pedidos?",
            "sql": "SELECT COUNT(*) AS total FROM core_pedido LIMIT 200",
            "columns": ["total"],
            "rows": [{"total": 3}],
            "row_count": 1,
            "truncated": False,
            "meta": {"modelo": "mock-sql", "tokens_prompt": 10, "tokens_output": 5},
        },
    )

    resultado = perguntar("Quantos pedidos?", "jwt-123")

    assert resultado.sql.startswith("SELECT")
    assert resultado.columns == ["total"]
    assert resultado.rows == [{"total": 3}]
    assert resultado.row_count == 1
    assert resultado.truncated is False
    assert resultado.meta["modelo"] == "mock-sql"
    assert chamadas[0]["cabecalhos"]["Authorization"] == "Bearer jwt-123"


def test_perguntar_401_traduz_sessao_expirada(monkeypatch):
    _urlopen_fake(monkeypatch, erro=_http_error(401, '{"detail": "expirado"}'))

    with pytest.raises(AskSqlErro) as excinfo:
        perguntar("Qualquer pergunta", "token-velho")

    assert excinfo.value.status == 401


def test_perguntar_422_preserva_exemplos(monkeypatch):
    _urlopen_fake(
        monkeypatch,
        erro=_http_error(
            422,
            '{"detail": "fora do domínio", "examples": ["Quais pedidos?"]}',
        ),
    )

    with pytest.raises(AskSqlErro) as excinfo:
        perguntar("endereço?", "jwt")

    assert excinfo.value.status == 422
    assert str(excinfo.value) == "fora do domínio"
    assert excinfo.value.examples == ("Quais pedidos?",)


def test_perguntar_resposta_sem_sql_falha(monkeypatch):
    _urlopen_fake(monkeypatch, resposta={"question": "x"})

    with pytest.raises(AskSqlErro):
        perguntar("x", "jwt")


def test_perguntar_json_invalido_falha(monkeypatch):
    _urlopen_fake(monkeypatch, texto="not-json")

    with pytest.raises(AskSqlErro):
        perguntar("x", "jwt")


def test_erro_de_conexao_e_traduzido(monkeypatch):
    _urlopen_fake(monkeypatch, erro=error.URLError("connection refused"))

    with pytest.raises(AskSqlErro) as excinfo:
        perguntar("x", "jwt")

    assert "Não foi possível conectar" in str(excinfo.value)


def test_timeout_e_traduzido(monkeypatch):
    _urlopen_fake(monkeypatch, erro=TimeoutError())

    with pytest.raises(AskSqlErro) as excinfo:
        perguntar("x", "jwt")

    assert "demorou demais" in str(excinfo.value)


def test_http_error_sem_json_usa_mensagem_padrao(monkeypatch):
    _urlopen_fake(monkeypatch, erro=_http_error(503, "<html>fora do ar</html>"))

    with pytest.raises(AskSqlErro) as excinfo:
        perguntar("x", "jwt")

    assert "indisponível" in str(excinfo.value)
