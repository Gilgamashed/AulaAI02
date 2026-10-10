"""Testes de redação/PII e da bandeira `LLM_REDACAO_ATIVA` (Aula 14, item 4).

O item 3 da spec pede que PII e segredos não saiam do `llm_service`: nem para o
provedor, nem de volta na resposta, nem nos logs. A matriz de padrões abaixo é a
garantia de que cada classe de dado é coberta por um placeholder estável.

Dois pontos são deliberadamente testados:

* **idempotência** — `redigir(redigir(x)) == redigir(x)`: um log que já passou
  pela camada não pode ser alterado de novo (nem criar placeholders aninhados);
* **a bandeira off** — desligar `LLM_REDACAO_ATIVA` devolve o comportamento
  transparente para desenvolvimento/benchmark; isso precisa ser *explícito*,
  não um default silencioso.
"""

from __future__ import annotations

import pytest

from core.llm.portas import LlmResposta, ProvedorLlm
from core.llm.redacao import redigir
from core.llm.servico import LlmService
from core.llm.circuit_breaker import CircuitBreaker
from core.llm.retry import RetryPolicy

pytestmark = pytest.mark.unit


class _ProvedorCaptura(ProvedorLlm):
    """Provedor que guarda o que recebeu e devolve um `texto` injetado."""

    def __init__(self, texto: str = "") -> None:
        self.recebidas: list[dict[str, str]] = []
        self._texto = texto

    def completar(self, mensagens, *, temperature, max_tokens):
        self.recebidas = list(mensagens)
        conteudo = mensagens[-1]["content"] if mensagens else ""
        return LlmResposta(
            texto=self._texto or conteudo,
            tokens_prompt=10,
            tokens_output=5,
        )


def _servico(provedor: _ProvedorCaptura, *, redacao: bool):
    from concurrent.futures import ThreadPoolExecutor

    executor = ThreadPoolExecutor(max_workers=1)
    servico = LlmService(
        provedor,
        retry=RetryPolicy(max_tentativas=1, base_segundos=0.0, fator=1.0, jitter=False),
        breaker=CircuitBreaker(limite_falhas=5, cooldown_segundos=30.0),
        executor=executor,
        redacao_ativa=redacao,
    )
    return servico, executor


# =====================================================================
# Matriz de padrões
# =====================================================================
@pytest.mark.parametrize(
    ("entrada", "presente"),
    [
        pytest.param(
            "contato fulano@gmail.com", "[EMAIL]", id="email"
        ),
        pytest.param(
            "cpf 123.456.789-01", "[CPF_CNPJ]", id="cpf-pontuado"
        ),
        pytest.param(
            "cpf 12345678901", "[CPF_CNPJ]", id="cpf-sem-pontos"
        ),
        pytest.param(
            "cnpj 12.345.678/0001-90", "[CPF_CNPJ]", id="cnpj"
        ),
        pytest.param(
            "celular (11) 91234-5678", "[TELEFONE]", id="telefone"
        ),
        pytest.param(
            "celular +55 11 98765-4321", "[TELEFONE]", id="telefone-internacional"
        ),
        pytest.param(
            "origem 10.4.66.101", "[IP]", id="ipv4"
        ),
        pytest.param(
            "cartão 4555 1234 5678 9012", "[CARTAO]", id="cartao"
        ),
        pytest.param(
            "autorização Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.sig1234567890",
            "[TOKEN]",
            id="jwt-bearer",
        ),
        pytest.param(
            "chave sk-proj-0Qr9ZfqLtmXkPvW2nYcJ8m5B1SaIdGeHtUw3rD6o",
            "[TOKEN]",
            id="chave-provedor",
        ),
        pytest.param(
            "redis://:senhasecreta@host:6379/0", "[CREDENCIAL]", id="url-com-credencial"
        ),
        pytest.param(
            "senha=minha-senha-aqui", "[SEGREDO]", id="chave-senha"
        ),
        pytest.param(
            "password: secreto123", "[SEGREDO]", id="chave-password"
        ),
        pytest.param(
            "api_key=abc123def456", "[SEGREDO]", id="chave-api-key"
        ),
    ],
)
def test_redige_cada_classe_de_dado(entrada, presente):
    texto = redigir(entrada)

    assert presente in texto
    # Nenhum padrão deveria "sobreviver" por inteiro: a classe de dado some,
    # fica só o placeholder (e o texto ao redor).
    for fragmento in ("fulano@gmail.com", "123.456.789-01", "91234-5678"):
        assert fragmento not in texto


def test_texto_sem_dados_sensiveis_nao_e_alterado():
    original = "o checkout derrubou a conexão com o broker às 14h03"
    assert redigir(original) == original


def test_redacao_e_idempotente():
    sensivel = "aluno maisa@fiap.com.br cpf 321.654.987-00"
    uma_vez = redigir(sensivel)
    duas_vezes = redigir(uma_vez)

    assert duas_vezes == uma_vez


# =====================================================================
# Aplicação no serviço (bandeira on/off)
# =====================================================================
def test_servico_redige_antes_do_provedor_e_na_resposta():
    provedor = _ProvedorCaptura(texto="cliente fulano@gmail.com aguardando")
    servico, executor = _servico(provedor, redacao=True)
    try:
        resposta = servico.completar(
            [{"role": "user", "content": "log: fulano@gmail.com pagou "}],
            temperature=0.2,
            max_tokens=100,
        )
    finally:
        executor.shutdown(wait=True)

    # O provedor nunca vê a PII crua...
    assert "fulano@gmail.com" not in provedor.recebidas[-1]["content"]
    assert "[EMAIL]" in provedor.recebidas[-1]["content"]
    # ...e o que volta para o chamador também vem redigido (eco do provedor).
    assert "fulano@gmail.com" not in resposta.texto
    assert "[EMAIL]" in resposta.texto


def test_servico_com_redacao_desligada_nao_redige():
    provedor = _ProvedorCaptura(texto="cliente fulano@gmail.com aguardando")
    servico, executor = _servico(provedor, redacao=False)
    try:
        resposta = servico.completar(
            [{"role": "user", "content": "log: fulano@gmail.com pagou "}],
            temperature=0.2,
            max_tokens=100,
        )
    finally:
        executor.shutdown(wait=True)

    assert "fulano@gmail.com" in provedor.recebidas[-1]["content"]
    assert "fulano@gmail.com" in resposta.texto
    assert "[EMAIL]" not in resposta.texto