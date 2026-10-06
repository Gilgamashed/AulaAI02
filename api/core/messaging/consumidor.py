"""Consumidor da Aula 9: o *worker* do evento `PedidoCriado`.

Executado pelo management command `consumir_pedidos` (ver também o serviço
`worker` do docker-compose). Uma iteração do laço, para uma mensagem:

    basic_consume (auto_ack=False)
        │
        ├─ 1. desserializa e valida contra o contrato v1
        │       └─ inválido ────────────────────────────────> DLQ (terminal)
        │
        ├─ 2. reserva a janela de idempotência (Redis SET NX EX)
        │       └─ já reservada ──> `PedidoDuplicado` + ack (sem efeito)
        │
        ├─ 3. aplica o efeito: UPDATE condicional `pendente -> processado`
        │       ├─ 0 linhas e pedido já processado ──> `PedidoDuplicado` + ack
        │       └─ 0 linhas e pedido divergente/ausente ───────────────> DLQ
        │
        ├─ 4a. sucesso ──> confirma a janela, log, `ack`
        └─ 4b. falha recuperável
                ├─ tentativa < max_reentregas ──> republica na fila de retry
                │                              do degrau (TTL no broker),
                │                              conta tentativa, `ack`
                └─ tentativas esgotadas ─────> pedido marcado como `falha`
                                               e mensagem na DLQ, `ack`

Princípio que organiza o código: **o `ack` vem sempre por último, e só depois
que a mensagem foi resolvida de fato** — por efeito aplicado, por republicação
confirmada, ou por descarte consciente (duplicata). A ordem inversa é o
caminho clássico do "evento perdido": o processo morre entre o `ack` e o
trabalho, e ninguém percebe.

`prefetch_count=1` (uma mensagem em trânsito por worker) é coerente com essa
garantia: enquanto o efeito não está confirmado, o worker não puxa a próxima.
"""

from __future__ import annotations

import json
import logging
import signal
import time
from typing import Any

import pika
from django.conf import settings
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from .. import models
from . import dedupe
from .contracts import ContratoInvalido, PedidoCriado, validar_pedido_criado
from .erros import descrever
from .metricas import DLQ, DUPLICADO, FALHA, PROCESSADO, mensageria_metrics
from .produtor import com_tentativa, republicar
from .topologia import (
    HEADER_TENTATIVA,
    Topologia,
    abrir_conexao,
    declarar_topologia,
)

logger = logging.getLogger("core.messaging")

# Estados que o worker pode avançar para `processado`. `processado` está
# fora de propósito: é a guarda contra o efeito duplicado no banco.
ESTADOS_PROCESSAVEIS = (
    models.Pedido.PENDENTE,
    models.Pedido.PENDENTE_PUBLICACAO,
    models.Pedido.FALHA,
)


class MensagemIncorreta(Exception):
    """Falha TERMINAL: reentregar não muda nada, então vai direto para a DLQ.

    Difere de uma exceção qualquer do banco, que pode ser transitória. Aqui a
    mensagem está logicamente errada: o pedido não existe, ou a chave de
    idempotência não é a do pedido. Reprocessar dez vezes reproduz o mesmo
    erro e só gasta broker.
    """


class FalhaInjetada(Exception):
    """Falha **de propósito** (header `X-Simular-Falha` no POST).

    Não é um bug: é o mecanismo que prova, ponta a ponta e a cada aula, que a
    escada de reentrega e a DLQ funcionam de verdade — com um pedido real, um
    log por tentativa e a mensagem parada em `pedidos.criados.dlq` no fim.

    Recupéravel por definição (é uma exceção comum no laço), então segue o
    mesmo caminho de qualquer falha transitória: reentrega com backoff e, ao
    esgotar, DLQ.
    """


class Consumidor:
    """Laço de consumo com política de reentrega e DLQ."""

    def __init__(self, fila: str | None = None, max_mensagens: int | None = None) -> None:
        self.fila = fila or settings.PEDIDO_FILA
        self.max_mensagens = max_mensagens
        self.recebidas = 0
        self.conexao: pika.BlockingConnection | None = None
        self.canal: Any = None
        self._topologia: Topologia | None = None
        self._parando = False

    @property
    def topologia(self) -> Topologia:
        """Topologia já declarada no canal.

        Property (e não atributo) porque todo uso é posterior a
        `declarar_topologia`: nenhuma mensagem é consumida antes disso. A
        checagem troca um `AttributeError` sobre `None` — que só apareceria
        em produção, no meio do tratamento de erro — por uma mensagem que diz
        o que aconteceu.
        """
        if self._topologia is None:
            raise RuntimeError("topologia ainda não declarada: o worker não está consumindo")
        return self._topologia

    def descricao_destino(self) -> str:
        """Texto do destino, para o console do management command.

        Existe para que `consumir_pedidos` sirva aos dois brokers com o mesmo
        código: cada consumidor sabe descrever a si próprio.
        """
        return f"a fila AMQP '{self.fila}'"

    # ------------------------------------------------------------------
    # Ciclo de vida
    # ------------------------------------------------------------------
    def rodar(self) -> dict[str, Any]:
        """Consome até parar (SIGTERM, `--max-mensagens` ou fila vazia)."""
        self.conexao = self._conectar_com_tentativas()
        with self.conexao:
            self.canal = self.conexao.channel()
            self._topologia = declarar_topologia(self.canal)
            # Sem isto, as republicações para retry/DLQ não teriam garantia de
            # entrega e o `ack` da original seria uma aposta.
            self.canal.confirm_delivery()
            # Uma mensagem em trânsito por vez (ver docstring do módulo).
            self.canal.basic_qos(prefetch_count=1)
            self.canal.basic_consume(
                queue=self.fila,
                on_message_callback=self.ao_receber,
                auto_ack=False,
            )
            self._instalar_parada_graciosa()
            logger.info(
                "worker iniciado",
                extra={
                    "evento": "WorkerIniciado",
                    "resultado": "ok",
                    "fila": self.fila,
                    "detalhe": {
                        **self.topologia.resumo(),
                        "prefetch": 1,
                        "max_mensagens": self.max_mensagens,
                    },
                },
            )
            try:
                self.canal.start_consuming()
            except KeyboardInterrupt:  # pragma: no cover - depende do terminal
                logger.info(
                    "worker interrompido pelo teclado",
                    extra={
                        "evento": "WorkerInterrompido",
                        "resultado": "ok",
                        "fila": self.fila,
                    },
                )

        resumo = mensageria_metrics.snapshot()
        resumo["fila"] = self.fila
        resumo["recebidas_no_processo"] = self.recebidas
        logger.info(
            "worker encerrado",
            extra={
                "evento": "WorkerEncerrado",
                "resultado": "ok",
                "fila": self.fila,
                "detalhe": resumo,
            },
        )
        return resumo

    def _conectar_com_tentativas(self, tentativas: int = 5) -> pika.BlockingConnection:
        """Conecta ao broker, tolerando o broker ainda estar subindo.

        Erro de conexão não é problema do consumidor: sair com código
        diferente de zero deixa o `restart: unless-stopped` do compose
        reexecutar o worker, o comportamento desejado para uma dependência
        que caiu (em vez de um processo vivo consumindo zumbido de erro).
        """
        ultimo_erro: Exception | None = None
        for tentativa in range(1, tentativas + 1):
            try:
                return abrir_conexao()
            except (pika.exceptions.AMQPError, OSError) as erro:
                ultimo_erro = erro
                logger.warning(
                    "broker indisponível; nova tentativa",
                    extra={
                        "evento": "WorkerSemConexao",
                        "resultado": "erro",
                        "fila": self.fila,
                        "tentativa": tentativa,
                        "erro": descrever(erro),
                    },
                )
                if tentativa < tentativas:
                    time.sleep(5)
        raise SystemExit(
            f"consumidor: broker indisponível após {tentativas} tentativas: {ultimo_erro}"
        )

    def _instalar_parada_graciosa(self) -> None:
        """SIGTERM/SIGINT param o consumo sem perder mensagem em trânsito.

        `docker compose stop` e `docker compose down` mandam SIGTERM. Como o
        `ack` é manual e chega por último, uma morte abrupta devolveria a
        mensagem à fila (comportamento correto, mas ruidoso no log). Parar de
        forma explícita torna o encerramento previsível.
        """

        def _parar(signum, _frame):
            if self._parando:
                return
            self._parando = True
            logger.info(
                "sinal de parada recebido; finalizando consumo",
                extra={
                    "evento": "WorkerParando",
                    "resultado": "ok",
                    "fila": self.fila,
                    "detalhe": signal.Signals(signum).name,
                },
            )
            if self.conexao and self.conexao.is_open:
                self.conexao.add_callback_threadsafe(self.canal.stop_consuming)

        signal.signal(signal.SIGTERM, _parar)
        signal.signal(signal.SIGINT, _parar)

    # ------------------------------------------------------------------
    # Tratamento de uma mensagem
    # ------------------------------------------------------------------
    def ao_receber(self, canal, metodo, propriedades, corpo: bytes) -> None:
        """Callback do `basic_consume`: trata e sempre resolve em ack/nack."""
        try:
            self._tratar(canal, metodo, propriedades, corpo)
        finally:
            # `--max-mensagens`: encerra o consumo DEPOIS de resolver a
            # mensagem atual (o `finally` garante isso mesmo se ela falhar).
            # `stop_consuming` dentro do callback é a forma suportada pelo
            # pika para sair de `start_consuming`.
            if self.max_mensagens and self.recebidas >= self.max_mensagens:
                logger.info(
                    "limite de mensagens atingido; encerrando consumo",
                    extra={
                        "evento": "WorkerLimiteAtingido",
                        "resultado": "ok",
                        "fila": self.fila,
                        "detalhe": f"{self.recebidas}/{self.max_mensagens} mensagens",
                    },
                )
                canal.stop_consuming()

    def _tratar(self, canal, metodo, propriedades, corpo: bytes) -> None:
        """Trata UMA mensagem, da validação do contrato ao `ack` final."""
        self.recebidas += 1
        mensageria_metrics.record_recebida()
        inicio = time.perf_counter()
        tentativa = self._tentativa(propriedades)

        try:
            evento = self._validar(corpo)
        except ContratoInvalido as erro:
            # Payload quebrado: reentregar não conserta JSON. DLQ imediata.
            self._mandar_para_dlq(
                canal, metodo, propriedades, corpo, tentativa, motivo=descrever(erro), invalido=True
            )
            return

        atraso_ms = max(0, int(time.time() * 1000) - evento.publicado_em_ms)
        logger.info(
            "mensagem recebida",
            extra={
                "evento": "MensagemRecebida",
                "resultado": "ok",
                "evento_id": evento.evento_id,
                "chave_idempotencia": evento.idempotency_key,
                "pedido_id": evento.pedido_id,
                "fila": self.fila,
                "tentativa": tentativa,
                "atraso_fila_ms": round(atraso_ms, 3),
            },
        )

        if not dedupe.reservar(evento):
            # Duplicata reconhecida pela janela: não há efeito a aplicar.
            canal.basic_ack(metodo.delivery_tag)
            mensageria_metrics.record(DUPLICADO)
            logger.info(
                "mensagem duplicada descartada",
                extra={
                    "evento": "PedidoDuplicado",
                    "resultado": "duplicado",
                    "evento_id": evento.evento_id,
                    "chave_idempotencia": evento.idempotency_key,
                    "pedido_id": evento.pedido_id,
                    "fila": self.fila,
                    "tentativa": tentativa,
                    "atraso_fila_ms": round(atraso_ms, 3),
                    "motivo": "chave de idempotência já reservada no Redis",
                },
            )
            return

        try:
            aplicado = self._aplicar_efeito(evento, tentativa)
        except MensagemIncorreta as erro:
            # Terminal: libera a janela (a chave não pode vazar) e joga na DLQ.
            dedupe.liberar(evento)
            self._registrar_falha(evento, descrever(erro), terminal=True)
            self._mandar_para_dlq(
                canal, metodo, propriedades, corpo, tentativa, motivo=descrever(erro)
            )
            return
        except Exception as erro:  # noqa: BLE001 - qualquer falha vira reentrega
            dedupe.liberar(evento)
            self._registrar_falha(evento, descrever(erro), terminal=False)
            self._reentregar_ou_dlq(
                canal, metodo, propriedades, corpo, evento, tentativa, erro
            )
            return

        # Sucesso (ou duplicata reconhecida no banco): a janela é confirmada
        # e só então a mensagem sai da fila.
        dedupe.confirmar(evento)
        canal.basic_ack(metodo.delivery_tag)
        duracao_ms = (time.perf_counter() - inicio) * 1000

        if aplicado:
            mensageria_metrics.record(PROCESSADO)
            logger.info(
                "pedido processado",
                extra={
                    "evento": "PedidoProcessado",
                    "resultado": "ok",
                    "evento_id": evento.evento_id,
                    "chave_idempotencia": evento.idempotency_key,
                    "pedido_id": evento.pedido_id,
                    "fila": self.fila,
                    "tentativa": tentativa,
                    "atraso_fila_ms": round(atraso_ms, 3),
                    "duracao_ms": round(duracao_ms, 3),
                },
            )
        else:
            # O `PedidoDuplicado` já foi logado em `_aplicar_efeito`, com o
                # motivo exato (UPDATE casou 0 linhas).
            mensageria_metrics.record(DUPLICADO)
            logger.info(
                "duplicata confirmada pelo banco",
                extra={
                    "evento": "MensagemEncerrada",
                    "resultado": "duplicado",
                    "evento_id": evento.evento_id,
                    "chave_idempotencia": evento.idempotency_key,
                    "pedido_id": evento.pedido_id,
                    "fila": self.fila,
                    "tentativa": tentativa,
                    "duracao_ms": round(duracao_ms, 3),
                },
            )

    # ------------------------------------------------------------------
    # Etapas
    # ------------------------------------------------------------------
    @staticmethod
    def _tentativa(propriedades) -> int:
        """Contador de tentativas que viaja nos headers da mensagem.

        O RabbitMQ também mantém o `x-death` (contadores próprios de
        dead-letter e TTL). Preferimos o nosso porque sobrevive a qualquer
        manipulação que o broker faça na mensagem e fica explícito no código.
        """
        headers = propriedades.headers or {}
        try:
            return int(headers.get(HEADER_TENTATIVA, 0))
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _validar(corpo: bytes) -> PedidoCriado:
        """Valida contra o contrato **do fluxo de pedidos**.

        Validador explícito (`validar_pedido_criado`), e não o despachante
        `validar`: o RabbitMQ desta base só transporta `PedidoCriado`, então
        qualquer outro tipo de evento aqui é um payload inesperado e precisa
        falhar no contrato — com o despachante, ele passaria pela validação e
        só cairia no efeito, depois de já ter passado pela janela de dedupe.
        """
        try:
            bruto = json.loads(corpo.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as erro:
            raise ContratoInvalido(f"corpo não é JSON UTF-8 válido: {erro}") from erro
        return validar_pedido_criado(bruto)

    def _aplicar_efeito(self, evento: PedidoCriado, tentativa: int) -> bool:
        """Aplica o estado do pedido. Devolve `True` se o efeito foi aplicado.

        O `UPDATE` condicional é a **segunda** barreira de idempotência (a
        primeira é a janela do Redis): mesmo que a chave de dedupe tenha
        expirado ou o Redis esteja fora, `status` deixando de ser `pendente`
        faz o `UPDATE` casar zero linhas e o consumidor trata como duplicata.

        A condição sobre `idempotency_key` fecha o outro lado da moeda: sem
        ela, uma mensagem desorientada (id certo, chave de outro pedido)
        processaria o pedido errado.

        A flag `simular_falha` é lida do **banco**, e não do evento, de
        propósito: ela é uma decisão operacional do pedido, não parte do
        contrato `PedidoCriado`, e o banco é a única autoridade sobre o
        estado atual.
        """
        if models.Pedido.objects.filter(pk=evento.pedido_id, simular_falha=True).exists():
            raise FalhaInjetada(
                "falha injetada (X-Simular-Falha): pedido marcado para falhar"
            )

        agora = timezone.now()
        with transaction.atomic():
            atualizados = models.Pedido.objects.filter(
                pk=evento.pedido_id,
                idempotency_key=evento.idempotency_key,
                status__in=ESTADOS_PROCESSAVEIS,
            ).update(
                status=models.Pedido.PROCESSADO,
                processado_em=agora,
                updated_at=agora,
                tentativas=F("tentativas") + 1,
                motivo_falha="",
            )

        if atualizados:
            return True

        # Zero linhas: ou o pedido já foi processado (duplicata real), ou a
        # mensagem não corresponde ao pedido. Não há corrida possível na
        # decisão: quem muda `status` é este mesmo worker.
        existente = models.Pedido.objects.filter(pk=evento.pedido_id).first()
        if existente is None:
            raise MensagemIncorreta(f"pedido {evento.pedido_id} não existe no banco")
        if existente.idempotency_key != evento.idempotency_key:
            raise MensagemIncorreta(
                "chave de idempotência do evento não confere com a do pedido"
            )
        logger.info(
            "efeito já aplicado anteriormente; descartando",
            extra={
                "evento": "PedidoDuplicado",
                "resultado": "duplicado",
                "evento_id": evento.evento_id,
                "chave_idempotencia": evento.idempotency_key,
                "pedido_id": evento.pedido_id,
                "fila": self.fila,
                "tentativa": tentativa,
                "motivo": "pedido já estava processado (UPDATE casou 0 linhas)",
            },
        )
        return False

    def _registrar_falha(self, evento: PedidoCriado, motivo: str, *, terminal: bool) -> None:
        """Grava a tentativa e a causa no pedido (evidência no banco).

        A escrita é separada da transação que aplicou o efeito: aquela foi
        desfeita pelo erro, e é justamente o registro da falha que precisa
        sobreviver a ele.
        """
        campos: dict[str, Any] = {
            "tentativas": F("tentativas") + 1,
            "motivo_falha": motivo[:200],
        }
        if terminal:
            campos["status"] = models.Pedido.FALHA
        models.Pedido.objects.filter(pk=evento.pedido_id).update(**campos)

    # ------------------------------------------------------------------
    # Política de falhas: reentrega com backoff ou DLQ
    # ------------------------------------------------------------------
    def _reentregar_ou_dlq(
        self, canal, metodo, propriedades, corpo, evento, tentativa: int, erro: Exception
    ) -> None:
        max_reentregas = settings.PEDIDO_MAX_REENTREGAS
        degraus = len(settings.PEDIDO_BACKOFF_SEGUNDOS)
        motivo = descrever(erro)

        # `tentativa >= max_reentregas`: a escada acabou. Já `tentativa + 1 >
        # degraus`: a política pede mais reentregas do que existem degraus
        # configurados — sem fila de retry para este degrau, a única rota
        # honesta é a DLQ (e o log deixa isso explícito).
        if tentativa >= max_reentregas:
            # A escada acabou: o pedido fica `falha` e a mensagem na DLQ. O
            # registro no banco é o que permite responder "o que aconteceu
            # com este pedido?" pelo `GET /pedidos/{id}`.
            self._registrar_falha(evento, motivo, terminal=True)
            self._mandar_para_dlq(
                canal, metodo, propriedades, corpo, tentativa, motivo=motivo
            )
            return
        if tentativa + 1 > degraus:
            logger.error(
                "política de reentrega inconsistente: faltam degraus de backoff",
                extra={
                    "evento": "PoliticaInconsistente",
                    "resultado": "erro",
                    "pedido_id": evento.pedido_id,
                    "tentativa": tentativa,
                    "detalhe": (
                        f"max_reentregas={max_reentregas} > "
                        f"degraus configurados={degraus}"
                    ),
                },
            )
            self._registrar_falha(evento, motivo, terminal=True)
            self._mandar_para_dlq(
                canal, metodo, propriedades, corpo, tentativa, motivo=motivo
            )
            return

        degrau = tentativa + 1
        try:
            republicar(
                canal,
                corpo,
                com_tentativa(propriedades, degrau, motivo=motivo),
                self.topologia.exchange_retry,
                self.topologia.routing_key_retry(degrau),
            )
        except (pika.exceptions.AMQPError, OSError) as erro_republicacao:
            # A republicação falhou: NÃO damos ack. O broker devolve a
            # mensagem à fila principal e ela é contada de novo. Perder a
            # mensagem aqui trocaria uma falha visível por uma perda
            # silenciosa.
            logger.error(
                "falha ao republicar para retry; mensagem volta à fila principal",
                extra={
                    "evento": "ReentregaFalhou",
                    "resultado": "erro",
                    "pedido_id": evento.pedido_id,
                    "fila": self.fila,
                    "tentativa": tentativa,
                    "erro": descrever(erro_republicacao),
                },
            )
            canal.basic_nack(metodo.delivery_tag, requeue=True)
            return

        canal.basic_ack(metodo.delivery_tag)
        mensageria_metrics.record(FALHA)
        mensageria_metrics.record_reentrega()
        logger.warning(
            "falha no processamento; mensagem reentregue",
            extra={
                "evento": "PedidoFalha",
                "resultado": "falha",
                "evento_id": evento.evento_id,
                "chave_idempotencia": evento.idempotency_key,
                "pedido_id": evento.pedido_id,
                "fila": self.topologia.fila_retry(degrau),
                "tentativa": degrau,
                # O atraso não é medido: é o `x-message-ttl` declarado na fila
                # de retry. Fica explícito para quem lê o log não achar que o
                # waited foi do worker.
                "duracao_ms": settings.PEDIDO_BACKOFF_SEGUNDOS[degrau - 1] * 1000,
                "erro": motivo,
                "motivo": (
                    f"reentrega {degrau}/{max_reentregas} em "
                    f"{settings.PEDIDO_BACKOFF_SEGUNDOS[degrau - 1]}s"
                ),
            },
        )

    def _mandar_para_dlq(
        self,
        canal,
        metodo,
        propriedades,
        corpo: bytes,
        tentativa: int,
        *,
        motivo: str,
        invalido: bool = False,
    ) -> None:
        """Move a mensagem para a DLQ (rota terminal) e encerra a tentativa."""
        if invalido:
            mensageria_metrics.record_invalida()

        try:
            republicar(
                canal,
                corpo,
                com_tentativa(propriedades, tentativa, motivo=motivo),
                self.topologia.exchange_dlx,
                self.topologia.routing_key,
            )
        except (pika.exceptions.AMQPError, OSError) as erro_dlq:
            logger.error(
                "falha ao enviar para a DLQ; mensagem volta à fila principal",
                extra={
                    "evento": "DlqFalhou",
                    "resultado": "erro",
                    "fila": self.fila,
                    "tentativa": tentativa,
                    "erro": descrever(erro_dlq),
                },
            )
            canal.basic_nack(metodo.delivery_tag, requeue=True)
            return

        canal.basic_ack(metodo.delivery_tag)
        mensageria_metrics.record(DLQ)
        logger.error(
            "mensagem encaminhada para a DLQ",
            extra={
                "evento": "PedidoDlq",
                "resultado": "dlq",
                "fila": self.topologia.fila_dlq,
                "tentativa": tentativa,
                "erro": motivo,
                "motivo": (
                    "contrato inválido (falha terminal, sem reentrega)"
                    if invalido
                    else f"tentativas esgotadas ({tentativa}/{settings.PEDIDO_MAX_REENTREGAS})"
                ),
            },
        )
