"""Janela de idempotência (Redis `SET NX EX`), comum aos dois fluxos.

Uma fila entrega **pelo menos uma vez**: a mesma mensagem pode chegar duas
vezes (reentrega após falha, reconexão do worker, republicação manual). O
objetivo aqui é simples: a segunda cópia é reconhecida e descartada sem
reaplicar o efeito.

Por que Redis e não só o banco
------------------------------
A spec pede "chave de deduplicação com prazo de validade (TTL)". O Redis dá
isso nativo (`SET ... EX`) e em uma operação atômica; no banco, um TTL
exigiria uma rotina de expurgo. Mas o Redis, sozinho, **não** garante a
idempotência do efeito — ele só filtra a maioria das duplicatas. A garantia
real está no `UPDATE` condicional do consumidor
(`Pedido.objects.filter(pk=..., status=PENDENTE).update(...)` e o
`Pagamento.objects.filter(pk=..., notificado_em__isnull=True).update(...)`): se
a chave sumiu (TTL expirou, Redis reiniciou) mas o efeito já aconteceu, o banco
impede a repetição. São duas camadas de propósito.

Uma janela, dois fluxos
-----------------------
`PedidoCriado` (fluxo `pedidos`) e `PagamentoRegistrado` (fluxo `pagamentos`)
usam a **mesma** janela, e é por isso que a chave carrega o nome do fluxo
(`contracts.PedidoCriado.chave_dedupe`). Os dois eventos compartilham a
`envelope` — inclusive o campo `idempotency_key`, que é um SHA-256 de 64 hex.
Sem o prefixo, a janela trataria um pagamento como duplicata do pedido a que ele
pertence, e o cliente nunca receberia a notificação. O prefixo é o que separa as
duas perguntas: "este pedido já foi processado?" e "este pagamento já foi
notificado?".

Ciclo de vida da chave
----------------------
    reservar (SET NX EX)  ── processamento OK ──> confirmada (o TTL passa a contar)
                        └─ falha               ──> liberada (DEL), para a
                                                    reentrega poder reprocessar

A liberação no caminho da falha é o detalhe que costuma faltar: sem ela, a
primeira tentativa marcaria a chave e todas as reentregas seriam tratadas
como duplicata — o pagamento nunca sairia da fila.

Toda degradação (backend ausente, Redis fora, falha ao confirmar ou liberar)
conta em `mensageria_metrics.dedupe_degradado`, que aparece no snapshot do
`WorkerEncerrado`. Assim "o Redis estava indisponível" deixa de ser uma
inferência a partir de três warnings e vira um número.
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.core.cache import InvalidCacheBackendError, caches
from django.core.cache.backends.base import BaseCache

from .contracts import Evento
from .erros import descrever
from .metricas import mensageria_metrics

logger = logging.getLogger("core.messaging")

# Alias do cache: aponta para o db 0 do Redis (ver settings.CACHES).
DEDUPE = "dedupe"
PREFIXO_CHAVE = "mensageria:idempotencia"


def _janela() -> BaseCache | None:
    """Cache de dedupe, ou `None` se não houver backend configurado.

    O `None` só acontece se alguém rodar a view ou o consumidor com uma
    configuração de settings sem o alias (ex.: um settings mínimo de teste).
    O consumidor trata isso como dedupe indisponível (fail-open), igual ao
    caso do Redis estar fora do ar.
    """
    try:
        return caches[DEDUPE]
    except (InvalidCacheBackendError, KeyError):
        return None


def _chave_cache(evento: Evento) -> str:
    """Chave real no Redis: `synapseshop:0:mensageria:idempotencia:<fluxo>:<chave>`.

    A chave de idempotência entra **crua**, sem passar por SHA-256: ela já é um
    hex de 64 caracteres quando o produtor a calcula
    (`views._chave_idempotencia`), e quando vem do header do cliente passa por
    SHA-256 antes de chegar aqui (`CharField(max_length=64)`). Ou seja, hashear
    de novo não acrescentaria nada e só custaria uma passada de CPU por
    mensagem. O prefixo do backend (`synapseshop:0:`) vem do próprio Django,
    então o que tooling precisar casar é o sufixo
    `mensageria:idempotencia:<fluxo>:<chave>` — e o `<fluxo>` é
    `pedidos`/`pagamentos`, o que torna a auditoria trivial
    (`redis-cli -n 0 keys 'mensageria:idempotencia:pagamentos:*'`).
    """
    return f"{PREFIXO_CHAVE}:{evento.chave_dedupe()}"


def reservar(evento: Evento) -> bool:
    """Tenta reservar a janela. `True` = primeira vez; `False` = duplicata.

    `SET NX` é atômico no Redis: dois workers recebendo a mesma mensagem ao
    mesmo tempo disputam a chave e apenas um ganha. Essa corrida é a razão de a
    operação ser `NX` e não `GET` seguido de `SET`.

    Em falha de conexão, devolve `True` (**fail-open**): o worker processa a
    mensagem e o `UPDATE` condicional no banco evita o efeito duplicado. A
    alternativa — fail-closed, devolver `False` — descartaria trabalho
    legítimo sempre que o Redis oscilasse, o que é pior para o negócio do que
    processar e detectar a duplicata mais tarde.
    """
    janela = _janela()
    if janela is None:
        _degradado(evento, "backend de deduplicação não configurado")
        return True
    try:
        return bool(janela.add(_chave_cache(evento), evento.pedido_id))
    except Exception as erro:  # noqa: BLE001 - qualquer falha do cache degrada
        _degradado(evento, descrever(erro))
        return True


def confirmar(evento: Evento) -> None:
    """Marca a janela como consumida com sucesso.

    Reescreve a chave com o TTL cheio em vez de apenas deixá-la: o prazo da
    janela conta a partir do **processamento concluído**, e não da chegada da
    mensagem. Assim uma mensagem que passou 65 s na escada de reentrega ainda
    fica protegida pelo TTL inteiro depois de ser processada.
    """
    _operacao(
        evento,
        lambda janela: janela.set(
            _chave_cache(evento),
            evento.pedido_id,
            settings.DEDUPE_TTL_SEGUNDOS,
        ),
        "não foi possível renovar a janela de deduplicação",
        "DedupeNaoConfirmado",
    )


def liberar(evento: Evento) -> None:
    """Libera a janela para que a reentrega possa reprocessar.

    Chamado em TODO caminho de falha. Sem esta liberação, a primeira tentativa
    marcaria a chave e todas as reentregas seriam tratadas como duplicata — o
    pedido nunca sairia da fila.
    """
    _operacao(
        evento,
        lambda janela: janela.delete(_chave_cache(evento)),
        "não foi possível liberar a janela de deduplicação",
        "DedupeNaoLiberado",
    )


def _operacao(evento: Evento, acao, mensagem_log: str, evento_log: str) -> None:
    """Executa uma escrita na janela, degradando em silêncio se falhar.

    `confirmar`/`liberar` nunca devem derrubar o processamento: se o Redis
    falhar ao confirmar, a garantia de idempotência restante é o `UPDATE`
    condicional no banco; se falhar ao liberar, o efeito colateral é a chave
    reservada sobreviver até o TTL — e o pedido, cujo status já é `processado`
    (e o pagamento, cujo `notificado_em` já foi gravado), protegem a si mesmos de
    qualquer forma.
    """
    janela = _janela()
    if janela is None:
        _degradado(evento, "backend de deduplicação não configurado")
        return
    try:
        acao(janela)
    except Exception as erro:  # noqa: BLE001 - degradação silenciosa
        # Não é só log: `confirmar`/`liberar` podem falhar **também** com o
        # Redis no ar (timeout, pool esgotado, valor serializado que o Redis
        # recusa). Contar aqui é o que dá ao `WorkerEncerrado` um número
        # honesto de quantas vezes a janela não pôde ser usada.
        mensageria_metrics.record_degradacao()
        logger.warning(
            mensagem_log,
            extra={
                "evento": evento_log,
                "resultado": "erro",
                "fluxo": evento.fluxo,
                "chave_idempotencia": evento.idempotency_key,
                "pedido_id": evento.pedido_id,
                "erro": descrever(erro),
            },
        )


def _degradado(evento: Evento, erro: str) -> None:
    """Registra que a janela de idempotência não pôde ser usada."""
    mensageria_metrics.record_degradacao()
    logger.warning(
        "janela de deduplicação indisponível; seguindo sem ela",
        extra={
            "evento": "DedupeDegradado",
            "resultado": "erro",
            "fluxo": evento.fluxo,
            "chave_idempotencia": evento.idempotency_key,
            "pedido_id": evento.pedido_id,
            "erro": erro,
            "motivo": (
                "fail-open: o UPDATE condicional no banco continua "
                "garantindo o efeito único"
            ),
        },
    )