"""Redação (redaction) de dados sensíveis antes do provedor e do log (Aula 14).

A spec pede pseudonimização/ocultação de Informações Pessoais Identificáveis
(PII) e segredos antes de enviar dados ao provedor de LLM e antes de qualquer
armazenamento em log. A regra do projeto é a da LGPD/RGPD: **não é por causa
do malicioso, é por causa do acidente** — um log que vaza um CPF ou um bearer
token é um incidente mesmo que ninguém o tenha lido.

`redigir` troca cada ocorrência por um placeholder invariável (`[EMAIL]`,
`[CPF]`, ...), padrão que o assistente e as métricas conseguem correlacionar
sem expor o valor. Regras:

- os padrões são conservadores e **superselecionantes**: antes de omitir um
  valor por erro, omitir demais (a redação nunca deve deixar PII passar);
- a ordem importa: emails e URLs com credenciais são tratados antes de CPF/
  telefone para não haver sobreposição de regex;
- é uma camada de defesa em profundidade: o adaptador HTTP do futuro também
  deve tratar no próprio transporte — a redação aqui garante o **boundary** do
  `llm_service`, independentemente do endpoint que o usar.
"""

from __future__ import annotations

import re

_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
# `://user:senha@host` — URL com credenciais embutidas (ex.: `redis://:x@h`).
_URL_CREDENCIAIS = re.compile(
    r"(?P<esquema>[a-z][a-z0-9+.-]*://)(?P<credencial>[^/\s@]+)@"
)
# CPF (000.000.000-00) e CNPJ (00.000.000/0000-00), com ou sem pontuação.
_CPF_CNPJ = re.compile(
    r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b|\b\d{11}\b|\b\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}\b|\b\d{14}\b"
)
# Telefones BR: (11) 91234-5678, 11 91234-5678, +55 11 98765-4321.
_TELEFONE = re.compile(
    r"\+?\d{0,2}\s?\(?\d{2}\)?\s?\d{4,5}-?\d{4}"
)
_IP = re.compile(
    r"\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b"
    r"|\b(?:[0-9a-fA-F]{1,4}:){7}[0-9a-fA-F]{1,4}\b"
)
# Cartões de 13 a 16 dígitos (Luhn deixa a validação real para o domínio).
_CARTAO = re.compile(r"\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b")
# Tokens e chaves: JWT, Bearer, sk-/chaves longas de alta entropia.
_TOKEN = re.compile(
    r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"
    r"|\bBearer\s+[A-Za-z0-9._~+/=-]{16,}"
    r"|\b[sbp]k[-_][A-Za-z0-9_-]{16,}\b"
    r"|\b[A-Z0-9]{24,}\b"
)
# `senha=...`, `password=...`, `token=...`, `api_key=...` em querystring/par.
_CHAVE_VALOR = re.compile(
    r"(?i)(password|passwd|senha|token|api[_-]?key|secret|authorization)"
    r"(=|\s*[:=]\s*)([^\s&\"']+)"
)

_PLACEHOLDERS: tuple[tuple[re.Pattern[str], str], ...] = (
    (_URL_CREDENCIAIS, r"\1[CREDENCIAL]@"),
    (_EMAIL, "[EMAIL]"),
    (_CPF_CNPJ, "[CPF_CNPJ]"),
    (_TELEFONE, "[TELEFONE]"),
    (_IP, "[IP]"),
    (_CARTAO, "[CARTAO]"),
    (_TOKEN, "[TOKEN]"),
    (_CHAVE_VALOR, r"\1\2[SEGREDO]"),
)


def redigir(texto: str) -> str:
    """Substitui PII/segredos por placeholders. Idempotente.

    Nenhuma entrada pode sair do `llm_service` sem passar por aqui; o retorno
    já sai redigido (defesa contra eco do provedor). Mantém o comprimento
    aproximado do original para não distorcer a estimativa de tokens.
    """
    resultado = texto
    for padrao, substituicao in _PLACEHOLDERS:
        resultado = padrao.sub(substituicao, resultado)
    return resultado