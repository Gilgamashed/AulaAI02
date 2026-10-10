"""Métricas do `llm_service` da Aula 14 (contadores em memória do processo).

A spec pede telemetria de **latência**, **taxa de erro** e **consumo de tokens
com estimativa de custo** no caminho do assistente. Como no `messaging/metricas.py`,
os contadores vivem no processo:

| Desfecho     | Significado                                                    |
| ------------ | -------------------------------------------------------------- |
| `sucesso`    | `completar` retornou uma `LlmResposta`                          |
| `falha`      | recuperável esgotou as tentativas (ou circuito registrou falha) |
| `terminal`   | erro que retentar não corrige (4xx/cliente) — não conta falha   |
| `bloqueada`  | fail-fast: circuito estava aberto, chamada nem chegou ao retry  |

`bloqueada` **não** soma em `chamadas` (é mutuamente exclusiva com os três
desfechos e não tem tokens nem latência). `chamadas` é o que passou do breaker.

Além dos desfechos, o coletor acumula `tokens_prompt`+`tokens_output`,
`custo_usd` (estimativa a partir das settings `LLM_CUSTO_*`) e o somatório de
`latencia_ms`, e expõe as derivadas `taxa_erro` (= `falhas / chamadas`) e
`latencia_media_ms`.

**Limite conhecido (assimétrico em relação ao cache):** distinto da Aula 8,
aqui o endpoint `/api/v1/llm/metrics/` faz sentido porque a API **é** quem chama
o `LlmService` — o número do processo exposto é o das requisições atendidas por
aquele worker. A agregação multi-worker/multi-instância (e por usuário) fica
registrada como pendência no README/issue para uma iteração futura. A evidência
passível de agregação offline é o **log estruturado JSON** (`core.llm`), que
sobrevive ao restart.
"""

from __future__ import annotations

import threading
from dataclasses import asdict, dataclass

SUCESSO = "sucesso"
FALHA = "falha"
TERMINAL = "terminal"
BLOQUEADA = "bloqueada"

DESFECHOS = (SUCESSO, FALHA, TERMINAL)


@dataclass
class LlmMetrics:
    """Contadores acumulados do `llm_service` no processo."""

    chamadas: int = 0
    bloqueadas: int = 0
    sucessos: int = 0
    falhas: int = 0
    terminais: int = 0
    tokens_prompt: int = 0
    tokens_output: int = 0
    custo_usd: float = 0.0
    latencia_ms_total: float = 0.0

    def as_dict(self) -> dict:
        dados = asdict(self)
        dados["taxa_erro"] = round(self.falhas / self.chamadas, 4) if self.chamadas else 0.0
        dados["latencia_media_ms"] = (
            round(self.latencia_ms_total / self.chamadas, 2) if self.chamadas else 0.0
        )
        return dados


class LlmMetricsColetor:
    """Coletor thread-safe das métricas do `llm_service`."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._contadores = LlmMetrics()

    def record(
        self,
        desfecho: str,
        *,
        tokens_prompt: int = 0,
        tokens_output: int = 0,
        custo_usd: float = 0.0,
        latencia_ms: float = 0.0,
    ) -> None:
        with self._lock:
            contadores = self._contadores
            contadores.chamadas += 1
            if desfecho == SUCESSO:
                contadores.sucessos += 1
            elif desfecho == FALHA:
                contadores.falhas += 1
            elif desfecho == TERMINAL:
                contadores.terminais += 1
            contadores.tokens_prompt += tokens_prompt
            contadores.tokens_output += tokens_output
            contadores.custo_usd += custo_usd
            contadores.latencia_ms_total += latencia_ms

    def record_bloqueada(self) -> None:
        """Fail-fast por circuito aberto: não soma em `chamadas`."""
        with self._lock:
            self._contadores.bloqueadas += 1

    def snapshot(self) -> dict:
        with self._lock:
            return self._contadores.as_dict()

    def reset(self) -> None:
        with self._lock:
            self._contadores = LlmMetrics()


# Instância única do processo da API (mesmo processo que atende /assist).
llm_metrics = LlmMetricsColetor()