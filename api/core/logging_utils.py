"""Utilitários de logging das Aulas 8 (cache-aside), 9 (RabbitMQ) e 10 (Kafka).

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

Sobre a Aula 10: os nomes de evento (`PedidoPublicado`, `PedidoProcessado`,
`PedidoFalha`, `PedidoDlq`, `PedidoDuplicado`, `MensagemRecebida`) são os
**mesmos** dos dois brokers, e `broker` distingue a linha. É essa escolha que
permite comparar as duas execuções com o mesmo filtro de log
(`"evento": "PedidoProcessado"`) e que faz o `--analisar-logs` do
`measure_messaging.py` funcionar sem nenhum ramo por broker.
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
    # Aula 11 (segundo fluxo): com dois fluxos no mesmo broker, `pedido_id` sozinho
    # não identifica a entidade do log — um pagamento e um pedido do mesmo
    # número existem. `pagamento_id` é o par que fecha a identificação, e
    # `fluxo` diz de qual dos dois streams a linha veio (é também o que permite
    # filtrar `worker-kafka` e `worker-pagamentos` com o mesmo `grep`).
    "pagamento_id",
    "fluxo",
    "tentativa",
    "atraso_fila_ms",
    "duracao_ms",
    # Aula 10 (replayer): o tempo entre `resume()` da partição e a mensagem
    # voltar a ser entregue. É o que separa o backoff **declarado** do
    # backoff **pago** — o laço do replayer visita os degraus em sequência, e
    # essa espera é o que falta para acrescentar a 45 s do degrau 3.
    "espera_ms",
    # `idade_ms` é o **par** de `duracao_ms` no log de espera do replayer: já
    # passou este tempo desde a reentrega. Sem ele, o `RetryAguardando` dizia
    # quanto faltava mas não quanto já tinha custado, e os dois juntos são o que
    # fecha a conta do backoff declarado contra o pago.
    "idade_ms",
    "fila",
    "erro",
    # Aula 10 (Kafka): coordenadas do log no espaço do log distribuído. Com
    # broker + tópico + partição + offset, qualquer linha pode ser reencontrada
    # no histórico (é literalmente um `kafka-console-consumer --offset`), e
    # `grupo` diz quem lia o que — as três perguntas que o `fila` sozinha
    # (equivalente AMQP) não responde. `destino` aparece no log do replayer,
    # onde a informação que importa é para onde a mensagem foi devolvida.
    "broker",
    "topico",
    "particao",
    "offset",
    "grupo",
    "destino",
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
