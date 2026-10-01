"""Utilitários de logging das Aulas 8 (cache-aside) e 9 (mensageria).

O logger `core.cache` (configurado em `config/settings.py`) emite **uma linha
JSON por evento** de cache. O logger `core.messaging` faz o mesmo pelos
eventos de mensageria (publicação, consumo, duplicata, reentrega, DLQ). O
objetivo é duplo:

1. **Didático**: a demonstração ao vivo do ciclo *miss → preenchimento → hit*
   fica legível em `docker compose logs -f api` (basta filtrar por
   `"resultado": "miss"`), sem precisar de um parser de texto. Na Aula 9 é a
   mesma ideia para o ciclo *publicado → consumido → reentregue → DLQ*.
2. **Operacional**: campos estáveis (`evento`, `chave`, `namespace`,
   `resultado`, `ttl_s`, `latencia_ms`, `tentativa`) são exatamente o que um
   dashboard de métricas vai consumir na Aula 19.

Registro em log **estruturado** significa que o dado é separado por campos
nomeados, não concatenado em texto livre — é o que permite agregá-lo depois.
"""

import json
import logging
from datetime import datetime, timezone
from typing import Any

# Campos extras repassados via `logger.info(json.dumps(...), extra={...})`.
# A lista é explícita para o formatter nunca vazar um segredo por engano.
CAMPOS_EVENTO = (
    "evento",
    "namespace",
    "chave",
    "resultado",
    "ttl_s",
    "latencia_ms",
    "preenchimento_ms",
    "motivo",
    "entidade",
    "entidade_id",
    "detalhe",
    # Aula 9 (mensageria): rastreabilidade do evento entre produtor e
    # consumidor. `evento_id` e `chave_idempotencia` ligam uma linha do log
    # da API a uma linha do log do worker; `tentativa`/`atraso_fila_ms`
    # tornam visíveis a reentrega e o tempo que a mensagem passou na fila;
    # `duracao_ms` isola o trabalho de dentro do consumidor do espera.
    "evento_id",
    "chave_idempotencia",
    "pedido_id",
    "tentativa",
    "atraso_fila_ms",
    "duracao_ms",
    "fila",
    "erro",
)


class JsonLogFormatter(logging.Formatter):
    """Formata qualquer `LogRecord` como uma única linha JSON.

    Usado via `"()"` no dict `LOGGING` do Django. A formatação é
    *defensiva*: campos ausentes simplesmente não entram no JSON, e
    qualquer valor não serializável vira `str(...)` em vez de quebrar o log.
    """

    def format(self, record: logging.LogRecord) -> str:
        # `created` é o timestamp do próprio logging (não do relógio do
        # container): é a hora real em que o evento ocorreu.
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z"),
            "level": record.levelname,
            "logger": record.name,
        }
        # Copia apenas os campos conhecidos (whitelist) do `extra`.
        for campo in CAMPOS_EVENTO:
            valor = getattr(record, campo, None)
            if valor is not None:
                payload[campo] = valor
        # A mensagem em si entra como `mensagem` (usada nos avisos de erro,
        # que não têm os campos estruturados preenchidos).
        if record.getMessage():
            payload["mensagem"] = record.getMessage()
        return json.dumps(payload, ensure_ascii=False, default=str)
