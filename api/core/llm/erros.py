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

# `Tipo: mensagem` para os logs JSON — ou só o tipo quando sem mensagem.
# Implementação única em `core.erros` (a mesma da mensageria); o re-export
# mantém o caminho `core.llm.erros.descrever` estável para retry/servico.
from ..erros import descrever as descrever


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


class LlmModeloIndisponivel(LlmErroCliente):
    """O modelo pedido não está disponível no provedor (HTTP 404).

    É terminal para retry, mas elegível ao fallback de disponibilidade: não
    adianta repetir o mesmo nome de modelo, mas o mock pode atender a demo.
    """


class RespostaInvalida(LlmTerminal):
    """O provedor respondeu, mas o corpo não segue o contrato esperado."""


class RespostaBloqueada(RespostaInvalida):
    """O provedor bloqueou a resposta por segurança/conteúdo.

    Distinta de resposta vazia/malformada de propósito: bloqueio de segurança
    é terminal e **não** pode cair para o mock.
    """

    def __init__(self, mensagem: str, *, motivo: str = "") -> None:
        super().__init__(mensagem)
        self.motivo = motivo


class LlmIndisponivel(LlmErro):
    """Provedor indisponível do ponto de vista do chamador."""


class CircuitoAberto(LlmIndisponivel):
    """O circuit breaker recusou a chamada antes de ela chegar ao provedor."""