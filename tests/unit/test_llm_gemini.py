"""Testes do provedor Gemini e da seleção por `LLM_PROVIDER` (Aula 25)."""

from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest

from core.llm import erros
from core.llm.gemini import MODELO_PADRAO, ProvedorGemini
from core.llm.servico import _montar

pytestmark = pytest.mark.unit


class _Usage:
    prompt_token_count = 12
    candidates_token_count = 7


class _Resposta:
    def __init__(self, texto: str = "resposta do gemini") -> None:
        self.text = texto
        self.usage_metadata = _Usage()


class _RespostaComCandidatos:
    def __init__(
        self,
        *,
        texto: str = "",
        finish_reason: str | None = None,
        block_reason: str | None = None,
    ) -> None:
        self.text = texto
        self.usage_metadata = _Usage()
        self.candidates = [
            SimpleNamespace(finish_reason=finish_reason, content=None)
        ]
        self.prompt_feedback = SimpleNamespace(block_reason=block_reason)


class _Modelos:
    def __init__(self, *, resposta=None, erro: Exception | None = None) -> None:
        self.resposta = resposta or _Resposta()
        self.erro = erro
        self.chamadas: list[dict] = []

    def generate_content(self, **kwargs):
        self.chamadas.append(kwargs)
        if self.erro is not None:
            raise self.erro
        return self.resposta


class _Cliente:
    def __init__(self, modelos: _Modelos) -> None:
        self.models = modelos


class _ErroHttp(Exception):
    def __init__(self, code: int, *, retry_after: str | None = None) -> None:
        super().__init__(f"HTTP {code}")
        self.code = code
        headers = {"retry-after": retry_after} if retry_after else {}
        self.response = SimpleNamespace(status_code=code, headers=headers)


def _provedor(modelos: _Modelos, **kwargs) -> ProvedorGemini:
    return ProvedorGemini(
        api_key="chave-de-teste",
        modelo="gemini-3.5-flash",
        timeout_segundos=2.0,
        cliente=_Cliente(modelos),
        **kwargs,
    )


def test_chave_ausente_falha_com_configuracao_invalida():
    with pytest.raises(erros.LlmConfiguracaoInvalida, match="GEMINI_API_KEY"):
        ProvedorGemini(api_key="  ", modelo="gemini-3.5-flash")


def test_mapeia_system_e_user_para_o_sdk():
    modelos = _Modelos()
    provedor = _provedor(modelos)

    provedor.completar(
        [
            {"role": "system", "content": "Você é objetivo."},
            {"role": "user", "content": "Explique o log."},
        ],
        temperature=0.2,
        max_tokens=128,
    )

    chamada = modelos.chamadas[0]
    assert chamada["model"] == "gemini-3.5-flash"
    assert chamada["config"]["system_instruction"] == "Você é objetivo."
    assert chamada["config"]["temperature"] == 0.2
    assert chamada["config"]["max_output_tokens"] == 128
    assert chamada["config"]["thinking_config"] == {"thinking_budget": 0}
    assert chamada["contents"] == [
        {"role": "user", "parts": [{"text": "Explique o log."}]}
    ]


def test_converte_historico_assistant_para_model():
    modelos = _Modelos()
    provedor = _provedor(modelos)

    provedor.completar(
        [
            {"role": "user", "content": "Pergunta"},
            {"role": "assistant", "content": "Resposta anterior"},
            {"role": "user", "content": "Continua"},
        ],
        temperature=0.0,
        max_tokens=32,
    )

    papeis = [item["role"] for item in modelos.chamadas[0]["contents"]]
    assert papeis == ["user", "model", "user"]


def test_tokens_vem_dos_metadados_do_provedor():
    provedor = _provedor(_Modelos())

    resposta = provedor.completar(
        [{"role": "user", "content": "oi"}],
        temperature=0.0,
        max_tokens=16,
    )

    assert resposta.texto == "resposta do gemini"
    assert resposta.tokens_prompt == 12
    assert resposta.tokens_output == 7


def test_resposta_vazia_vira_resposta_invalida():
    provedor = _provedor(_Modelos(resposta=_Resposta(texto="   ")))

    with pytest.raises(erros.RespostaInvalida):
        provedor.completar(
            [{"role": "user", "content": "oi"}],
            temperature=0.0,
            max_tokens=16,
        )


def test_finish_reason_de_seguranca_vira_resposta_invalida():
    resposta = _RespostaComCandidatos(texto="texto parcial", finish_reason="SAFETY")
    provedor = _provedor(_Modelos(resposta=resposta))

    with pytest.raises(erros.RespostaInvalida, match="SAFETY"):
        provedor.completar(
            [{"role": "user", "content": "oi"}],
            temperature=0.0,
            max_tokens=16,
        )


def test_prompt_bloqueado_vira_resposta_invalida():
    resposta = _RespostaComCandidatos(block_reason="PROHIBITED_CONTENT")
    provedor = _provedor(_Modelos(resposta=resposta))

    with pytest.raises(erros.RespostaInvalida, match="PROHIBITED_CONTENT"):
        provedor.completar(
            [{"role": "user", "content": "oi"}],
            temperature=0.0,
            max_tokens=16,
        )


def test_finish_reason_stop_preserva_a_resposta():
    resposta = _RespostaComCandidatos(texto="ok", finish_reason="STOP")
    provedor = _provedor(_Modelos(resposta=resposta))

    saida = provedor.completar(
        [{"role": "user", "content": "oi"}],
        temperature=0.0,
        max_tokens=16,
    )

    assert saida.texto == "ok"


@pytest.mark.parametrize(
    ("codigo", "esperado"),
    [
        (400, erros.LlmErroCliente),
        (401, erros.LlmConfiguracaoInvalida),
        (403, erros.LlmConfiguracaoInvalida),
        (404, erros.LlmErroCliente),
        (429, erros.LlmRateLimit),
        (500, erros.LlmErroServidor),
        (503, erros.LlmErroServidor),
    ],
)
def test_erros_http_sao_traduzidos_para_a_taxonomia(codigo, esperado):
    provedor = _provedor(_Modelos(erro=_ErroHttp(codigo)))

    with pytest.raises(esperado):
        provedor.completar(
            [{"role": "user", "content": "oi"}],
            temperature=0.0,
            max_tokens=16,
        )


def test_rate_limit_preserva_retry_after():
    provedor = _provedor(_Modelos(erro=_ErroHttp(429, retry_after="7")))

    with pytest.raises(erros.LlmRateLimit) as capturado:
        provedor.completar(
            [{"role": "user", "content": "oi"}],
            temperature=0.0,
            max_tokens=16,
        )

    assert capturado.value.retry_after == 7.0


def test_timeout_e_conexao_sao_recuperaveis():
    class TimeoutDoCliente(Exception):
        pass

    class ConnectionDoCliente(Exception):
        pass

    timeout = ProvedorGemini(
        api_key="chave", cliente=_Cliente(_Modelos(erro=TimeoutDoCliente("timeout")))
    )
    with pytest.raises(erros.LlmTimeout):
        timeout.completar(
            [{"role": "user", "content": "oi"}], temperature=0.0, max_tokens=16
        )

    conexao = ProvedorGemini(
        api_key="chave", cliente=_Cliente(_Modelos(erro=ConnectionDoCliente("connect")))
    )
    with pytest.raises(erros.LlmConexao):
        conexao.completar(
            [{"role": "user", "content": "oi"}], temperature=0.0, max_tokens=16
        )


def test_erro_nao_expoe_a_chave():
    provedor = _provedor(_Modelos(erro=_ErroHttp(403)))

    with pytest.raises(erros.LlmConfiguracaoInvalida) as capturado:
        provedor.completar(
            [{"role": "user", "content": "oi"}],
            temperature=0.0,
            max_tokens=16,
        )

    assert "chave-de-teste" not in str(capturado.value)


def test_chave_nao_aparece_em_logs(caplog):
    provedor = _provedor(_Modelos(erro=_ErroHttp(403)))

    with caplog.at_level(logging.DEBUG, logger="core.llm"):
        with pytest.raises(erros.LlmConfiguracaoInvalida):
            provedor.completar(
                [{"role": "user", "content": "oi"}],
                temperature=0.0,
                max_tokens=16,
            )

    assert "chave-de-teste" not in caplog.text


def test_fabrica_mock_preserva_os_provedores_atuais():
    cfg = SimpleNamespace(
        LLM_PROVIDER="mock",
        LLM_MODEL="mock",
        LLM_MODEL_SQL="mock-sql",
        LLM_MODEL_DOCS="mock-docs",
        LLM_TIMEOUT_SEGUNDOS=1.0,
        GEMINI_API_KEY="",
    )

    assert type(_montar(cfg, "assist")._provedor).__name__ == "ProvedorMock"
    assert type(_montar(cfg, "sql")._provedor).__name__ == "ProvedorMockSql"
    assert type(_montar(cfg, "docs")._provedor).__name__ == "ProvedorMockDocs"


def test_fabrica_gemini_usa_modelo_padrao_quando_setting_ainda_e_mock(monkeypatch):
    capturado: dict = {}

    class ProvedorFake:
        def __init__(self, **kwargs) -> None:
            capturado.update(kwargs)

        def completar(self, *args, **kwargs):  # pragma: no cover - não chamado
            raise AssertionError

    monkeypatch.setattr("core.llm.servico.ProvedorGemini", ProvedorFake)
    cfg = SimpleNamespace(
        LLM_PROVIDER="gemini",
        LLM_MODEL="mock",
        LLM_MODEL_SQL="mock-sql",
        LLM_MODEL_DOCS="mock-docs",
        LLM_TIMEOUT_SEGUNDOS=20.0,
        GEMINI_API_KEY="chave",
    )

    servico = _montar(cfg, "sql")

    assert capturado["modelo"] == MODELO_PADRAO
    assert capturado["api_key"] == "chave"
    assert servico.modelo == MODELO_PADRAO


def test_fabrica_rejeita_provedor_desconhecido():
    cfg = SimpleNamespace(LLM_PROVIDER="outro")

    with pytest.raises(erros.LlmConfiguracaoInvalida, match="Valores aceitos"):
        _montar(cfg)
