"""Métricas do consumidor da Aula 9 (contadores em memória do processo).

Cada mensagem consumida cai em exatamente um **desfecho**:

| Desfecho           | Significado                                                |
| ------------------ | ---------------------------------------------------------- |
| `processado`       | o efeito de negócio foi aplicado (pedido → `processado`)    |
| `duplicado`        | reconheceu reenvio/duplicata e descartou sem efeito         |
| `falha`            | erro recuperável: reentregue pelo degrau da escada          |
| `dlq`              | erro terminal: contrato inválido ou tentativas esgotadas    |

E há um contador **independente** dos desfechos:

| Contador             | Significado                                                            |
| -------------------- | ---------------------------------------------------------------------- |
| `dedupe_degradado`   | a janela de idempotência não pôde ser usada (Redis fora, backend ausente, falha ao confirmar ou liberar) |

`dedupe_degradado` não é um desfecho porque não é mutuamente exclusivo: uma
mensagem pode falhar (`falha`) e ainda assim ter registrado degradação do
dedupe no mesmo processamento. Ele existe para responder "quantas vezes o
Redis esteve indisponível para este worker", que é uma pergunta de
disponibilidade, não de resultado de negócio.

**Limite conhecido (assimétrico em relação à Aula 8):** estes contadores
morrem com o processo do worker. Eles não viram um endpoint HTTP de propósito
— o processo que atenderia `/api/v1/mensageria/metrics/` é o da API, que
*não* roda o consumidor, então o número exposto seria sempre zero (ou pior:
parcial, se houvesse produtor ali). A evidência da spec é o **log
estruturado** (uma linha JSON por desfecho, com `tentativa` e
`atraso_fila_ms`), que sobrevive ao restart e pode ser agregado depois — e é
também o que `scripts/measure_messaging.py` consome.
"""

from __future__ import annotations

import threading
from dataclasses import asdict, dataclass

PROCESSADO = "processado"
DUPLICADO = "duplicado"
FALHA = "falha"
DLQ = "dlq"
DEDUPE_DEGRADADO = "dedupe_degradado"

DESFECHOS = (PROCESSADO, DUPLICADO, FALHA, DLQ)
# Não é desfecho: ver a docstring do módulo. É contado à parte justamente
# para poder coexistir com `falha`/`processado` numa mesma mensagem.
CONTADORES_INDEPENDENTES = (DEDUPE_DEGRADADO,)


@dataclass
class MensageriaMetrics:
    """Contadores acumulados do consumidor."""

    recebidas: int = 0
    processadas: int = 0
    duplicadas: int = 0
    falhas: int = 0
    reentregas: int = 0
    invalidas: int = 0
    dlq: int = 0
    dedupe_degradado: int = 0

    def as_dict(self) -> dict:
        dados = asdict(self)
        # Taxa de duplicatas sobre o que saiu da fila de fato: é o número que
        # diz quanto a janela de idempotência realmente segurou.
        saidas = self.processadas + self.duplicadas
        dados["taxa_duplicatas"] = round(self.duplicadas / saidas, 4) if saidas else 0.0
        return dados


class MensageriaMetricsColetor:
    """Coletor thread-safe dos desfechos de consumo."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._contadores = MensageriaMetrics()

    def record(self, desfecho: str) -> None:
        with self._lock:
            contadores = self._contadores
            if desfecho == PROCESSADO:
                contadores.processadas += 1
            elif desfecho == DUPLICADO:
                contadores.duplicadas += 1
            elif desfecho == FALHA:
                contadores.falhas += 1
            elif desfecho == DLQ:
                contadores.dlq += 1
            elif desfecho == DEDUPE_DEGRADADO:
                contadores.dedupe_degradado += 1

    def record_recebida(self) -> None:
        with self._lock:
            self._contadores.recebidas += 1

    def record_degradacao(self) -> None:
        """Conta uma vez que a janela de idempotência não pôde ser usada.

        Entrada própria em vez de `record(DEDUPE_DEGRADADO)` para o chamador
        (`dedupe.py`) não precisar conhecer a constante: quem degrada é o
        dedupe, e o que ele tem a dizer é "degradei", não "registrei o
        desfecho X".
        """
        with self._lock:
            self._contadores.dedupe_degradado += 1

    def record_reentrega(self) -> None:
        with self._lock:
            self._contadores.reentregas += 1

    def record_invalida(self) -> None:
        with self._lock:
            self._contadores.invalidas += 1

    def snapshot(self) -> dict:
        with self._lock:
            return self._contadores.as_dict()

    def reset(self) -> None:
        with self._lock:
            self._contadores = MensageriaMetrics()


# Instância única do processo do worker.
mensageria_metrics = MensageriaMetricsColetor()
