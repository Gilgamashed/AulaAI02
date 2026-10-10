"""Taxonomia de exceções do llm_service (Aula 14).

A camada de IA precisa trocar informações com um provedor que **não está sob o
nosso controle**. Para que a resiliência não precise saber de detalhes do
fornecedor, esta taxonomia é **neutra de provedor**: nenhuma classe aqui sabe
se o provedor real será OpenAI, Anthropic ou outro. O mock de hoje e o adaptador
HTTP do futuro mapeiam os erros do fornecedor para estas classes, e a política
de retry decide a partir delas:

- `LlmRecuperavel` — vale retentar (timeout, conexão, rate limit, 5xx).
- `LlmTerminal` — retentar não adianta (4xx do cliente, resposta malformada).
- `LlmIndisponivel` (`CircuitoAberto`) — indisponível do ponto de vista do
  chamador: ou o circuito estava aberto, ou as tentativas se esgotaram.
"""

from __future__ import annotations


class LlmErro(Exception):
    """Erro base de toda a camada de IA."""


class LlmConfiguracaoInvalida(LlmErro):
    """Configuração do llm_service incoerente (ex.: provedor desconhecido)."""


class LlmRecuperavel(LlmErro):
    """Falha passível de retry: o provedor continua existindo e pode responder."""


class LlmTimeout(LlmRecuperavel):
    """O provedor não respondeu dentro do deadline configurado."""


class LlmConexao(LlmRecuperavel):
    """Falha de transporte (rede, DNS, socket) até o provedor."""


class LlmRateLimit(LlmRecuperavel):
    """O provedor devolveu limitação de taxa (HTTP 429 no provedor real).

    `retry_after`, quando presente, é o tempo (s) sugerido pelo provedor para a
    próxima tentativa — a política de retry pode respeitá-lo.
    """

    def __init__(self, mensagem: str, *, retry_after: float | None = None) -> None:
        super().__init__(mensagem)
        self.retry_after = retry_after


class LlmErroServidor(LlmRecuperavel):
    """Erro interno do provedor (HTTP 5xx no provedor real)."""


class LlmTerminal(LlmErro):
    """Falha que não adianta retentar."""


class LlmErroCliente(LlmTerminal):
    """Requisição rejeitada pelo provedor (HTTP 4xx no provedor real)."""


class RespostaInvalida(LlmTerminal):
    """O provedor respondeu, mas o corpo não segue o contrato esperado."""


class LlmIndisponivel(LlmErro):
    """Provedor indisponível do ponto de vista do chamador."""


class CircuitoAberto(LlmIndisponivel):
    """O circuit breaker recusou a chamada antes de ela chegar ao provedor."""


def descrever(exc: BaseException) -> str:
    """`Tipo: mensagem` para os logs JSON — ou só o tipo quando sem mensagem.

    Várias exceções de transporte são levantadas sem argumentos e `str(exc)`
    devolveria `""`; o tipo da exceção precisa entrar sempre no log (mesma regra
    de `core.messaging.erros.descrever`).
    """
    nome = type(exc).__name__
    mensagem = str(exc).strip()
    if not mensagem:
        return nome
    return f"{nome}: {mensagem}"