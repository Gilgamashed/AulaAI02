import hashlib
import json
import logging
import uuid
from decimal import Decimal
from typing import Any

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Count
from django.http import Http404, JsonResponse
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.response import Response
from rest_framework.views import APIView

from . import cache as cache_api
from .cache_metrics import cache_metrics
from .filters import ItemFilter
from .llm import (
    CircuitoAberto,
    LlmConfiguracaoInvalida,
    LlmIndisponivel,
    LlmTerminal,
    criar_llm_service,
)
from .llm.metricas import llm_metrics
from .messaging import broker as mensageria
from .models import Category, Item, Notificacao, Pagamento, Pedido
from .permissions import IsAdminRole
from .serializers import (
    AssistSerializer,
    CategorySerializer,
    ItemDetalheSerializer,
    ItemSerializer,
    NotificacaoSerializer,
    PagamentoSerializer,
    PagamentoSimularSerializer,
    PedidoCreateSerializer,
    PedidoSerializer,
)

logger = logging.getLogger("core.llm")


def health(request):
    # Aula 10: o broker ativo entra no health para que "qual mensageria está no
    # ar?" seja respondida por uma chamada, sem precisar ler o log nem inferir
    # do compose. `MENSAGERIA_BROKER` aparece cru de propósito: se alguém
    # digitou `KAFKA` (maiúsculo) ou `kakfa`, o valor bruto entrega o erro de
    # configuração enquanto `broker` mostra o fallback efetivamente usado.
    bruto = str(getattr(settings, "MENSAGERIA_BROKER", "")).strip().lower()
    return JsonResponse(
        {
            "status": "ok",
            "service": "synapseshop-api",
            "broker": mensageria.broker_ativo(),
            "MENSAGERIA_BROKER": bruto,
            # Aula 11: com dois fluxos, "qual mensageria está no ar?" não basta
            # para responder "o worker de pagamento está consumindo o tópico
            # certo?". `mensageria.resumo()` traz os dois fluxos com tópico,
            # grupo e DLQ de cada um.
            "fluxos": (mensageria.resumo().get("fluxos") or {})
            if mensageria.broker_ativo() == mensageria.KAFKA
            else None,
        }
    )


# =====================================================================
# Aula 8 — instrumentação do padrão cache-aside
# =====================================================================
# A lógica de leitura/escrita no Redis fica em `core/cache.py`; as views
# apenas escolhem a CHAVE (recurso + variante) e o TTL. O fluxo é sempre:
#
#     cache_aside(chave, ttl, namespace, produtor)
#         ├─ HIT  → devolve o payload do Redis (sem tocar no PostgreSQL)
#         └─ MISS → produtor() lê o banco e preenche o cache
#
# Na listagem a chave inclui o fingerprint dos parâmetros (página, filtros,
# busca e ordenação); no detalhe, apenas o identificador do registro.


class CachedReadMixin:
    """Regras de leitura com cache-aside compartilhadas pelos viewsets.

    Centraliza o que é comum às quatro leituras instrumentadas
    (listagem/detalhe de Item e Category) e deixa cada viewset responsável
    apenas por declarar suas chaves, TTLs e serializers.
    """

    def _list_payload(self):
        """Executa o fluxo padrão de listagem do DRF e devolve o **payload**.

        É o mesmo caminho de `ListModelMixin.list` (filtrar → paginar →
        serializar), mas devolvendo `response.data` em vez do `Response`, para
        que o objeto possa ser serializado para o Redis e re-emitido num HIT.

        Um `404` de página inválida continua ocorrendo normalmente: a
        exceção sobe dentro do produtor, antes de qualquer escrita no cache.
        """
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data).data
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data).data


# Matriz de permissões da Aula 7 (aplicada a Category e Item):
#   - GET list/detail  -> público (AllowAny): catálogo de leitura livre.
#   - POST             -> qualquer usuário autenticado (papel user ou admin).
#   - PUT/PATCH/DELETE -> exclusivos do papel admin (rotas administrativas).
# A implementação usa `get_permissions()`, que devolve permissões diferentes
# por ação — é o ponto do DRF onde cada verbo HTTP recebe sua regra.


class CategoryViewSet(CachedReadMixin, viewsets.ModelViewSet):
    """CRUD de categorias com permissões por ação, busca no Admin e cache."""

    queryset = Category.objects.annotate(items_count=Count("items")).order_by("name")
    serializer_class = CategorySerializer
    # Busca livre (SearchFilter do DRF, sem django-filter): ?search=smartphone.
    search_fields = ["name", "slug"]
    ordering_fields = ["name", "-created_at"]

    def get_permissions(self):
        if self.action in {"update", "partial_update", "destroy"}:
            # Editar/excluir são rotas administrativas (admin e superuser).
            return [IsAdminRole()]
        if self.action in {"create"}:
            # Inclusão de categoria exige autenticação (user ou admin).
            return [permissions.IsAuthenticated()]
        # Listar e detalhar permanecem públicos (AllowAny padrão).
        return [permissions.AllowAny()]

    # --- Aula 8: cache-aside -------------------------------------------
    def list(self, request, *args, **kwargs) -> Response:
        """Listagem cacheada (TTL de `CACHE_TTL_LIST`, padrão 60 s).

        A listagem de categorias faz um `GROUP BY` por causa do
        `annotate(items_count=...)`, então é uma das leituras que mais ganha
        com o cache.
        """
        chave = cache_api.list_key(
            cache_api.NS_CATEGORY_LIST,
            cache_api.fingerprint_de_lista(
                request, cache_api.PARAMETROS_LISTAGEM
            ),
        )
        payload = cache_api.cache_aside(
            chave,
            cache_api.ttl_listagem(),
            cache_api.NS_CATEGORY_LIST,
            self._list_payload,
        )
        return Response(payload)

    def retrieve(self, request, *args, **kwargs) -> Response:
        """Detalhe cacheado por `categoria:<id>` (TTL `CACHE_TTL_DETAIL`, 300 s)."""
        if cache_api.tem_parametros_de_filtro(
            request, cache_api.PARAMETROS_FILTRO_CATEGORY
        ):
            cache_api.bypass(
                cache_api.NS_CATEGORY_DETAIL,
                "detalhe com busca/ordenação: resposta pode variar por requisição",
            )
            return super().retrieve(request, *args, **kwargs)

        chave = cache_api.detail_key(
            cache_api.PREFIXO_CATEGORY, kwargs.get("pk")
        )
        payload = cache_api.cache_aside(
            chave,
            cache_api.ttl_detalhe(),
            cache_api.NS_CATEGORY_DETAIL,
            self._detail_payload,
        )
        return Response(payload)

    def _detail_payload(self) -> Any:
        """Produtor do detalhe: 404 se a categoria não existir (nunca cacheado)."""
        return self.get_serializer(self.get_object()).data


class ItemViewSet(CachedReadMixin, viewsets.ModelViewSet):
    """CRUD de produtos com paginação, filtros e cache (Aulas 7 e 8)."""

    queryset = Item.objects.select_related("category").order_by("-created_at")
    serializer_class = ItemSerializer
    # Filtros de domínio (django-filter) + busca livre + ordenação.
    filterset_class = ItemFilter
    search_fields = ["name", "brand", "model", "sku"]
    ordering_fields = ["name", "brand", "price", "-created_at"]

    def get_permissions(self):
        # Mesma matriz da categoria: editável apenas por admin.
        if self.action in {"update", "partial_update", "destroy"}:
            return [IsAdminRole()]
        if self.action in {"create"}:
            return [permissions.IsAuthenticated()]
        return [permissions.AllowAny()]

    # --- Aula 8: cache-aside -------------------------------------------
    def list(self, request, *args, **kwargs) -> Response:
        """Listagem cacheada em `item:list:g<geracao>:<fingerprint>` (60 s).

        A chave inclui um contador de geração: uma única alteração de
        qualquer produto incrementa o contador e invalida todas as páginas /
        variantes de uma vez (ver `core/cache.py`).
        """
        chave = cache_api.list_key(
            cache_api.NS_ITEM_LIST,
            cache_api.fingerprint_de_lista(
                request, cache_api.PARAMETROS_LISTAGEM_ITEM
            ),
        )
        payload = cache_api.cache_aside(
            chave,
            cache_api.ttl_listagem(),
            cache_api.NS_ITEM_LIST,
            self._list_payload,
        )
        return Response(payload)

    def retrieve(self, request, *args, **kwargs) -> Response:
        """Detalhe cacheado em `item:<id>` (TTL de `CACHE_TTL_DETAIL`, 300 s)."""
        if cache_api.tem_parametros_de_filtro(
            request, cache_api.PARAMETROS_FILTRO_ITEM
        ):
            cache_api.bypass(
                cache_api.NS_ITEM_DETALHE,
                "detalhe com filtro/busca: no cache devolveria 200 onde o "
                "banco devolve 404",
            )
            return super().retrieve(request, *args, **kwargs)

        chave = cache_api.detail_key(cache_api.PREFIXO_ITEM, kwargs.get("pk"))
        payload = cache_api.cache_aside(
            chave,
            cache_api.ttl_detalhe(),
            cache_api.NS_ITEM_DETALHE,
            self._detail_payload,
        )
        return Response(payload)

    def _detail_payload(self) -> Any:
        """Produtor do detalhe: 404 se o produto não existir (nunca cacheado)."""
        return self.get_serializer(self.get_object()).data

    @action(detail=True, methods=["get"], url_path="detalhes")
    def detalhes(self, request, pk: str | None = None) -> Response:
        """Consulta **pesada** de um produto, cacheada em `item:<id>:detalhes`.

        É o par "endpoint de dados específicos" da spec da Aula 8: além do
        produto, devolve a categoria com agregados de preço e os itens mais
        caros/recentes da categoria (4 consultas — ver
        `ItemDetalheSerializer`). O TTL é o mesmo do detalhe (300 s).
        """
        chave = cache_api.details_key(cache_api.PREFIXO_ITEM, pk)
        payload = cache_api.cache_aside(
            chave,
            cache_api.ttl_detalhe(),
            cache_api.NS_ITEM_DETALHES,
            self._detalhes_payload,
        )
        return Response(payload)

    def _detalhes_payload(self) -> Any:
        """Produtor da consulta pesada (4 consultas ao banco, só no MISS)."""
        item = self.get_object()  # 404 se o produto não existir
        return ItemDetalheSerializer(item).data


# =====================================================================
# Aula 9 — `POST /pedidos`: o produtor do evento `PedidoCriado`
# =====================================================================


def _chave_idempotencia(
    request, itens: list[dict], usuario_id: int, total: Decimal
) -> str:
    """Resolve a chave de idempotência do pedido (64 hex, sha256).

    Ordem de precedência:

    1. header `Idempotency-Key` do cliente — é quem dá controle ao cliente
       (reenvio de rede, duplo clique, retry de gateway);
    2. SHA-256 do próprio pedido (usuário + itens ordenados + total) —
       evita que a reentrega acidental de um POST sem header crie dois
       pedidos idênticos.

    O header é normalizado com `sha256` quando é longo: a chave precisa caber
    em `CharField(max_length=64)` e em um header AMQP.
    """
    bruto = (request.headers.get("Idempotency-Key") or "").strip()
    if bruto:
        if len(bruto) <= 64:
            return bruto
        return hashlib.sha256(bruto.encode("utf-8")).hexdigest()
    canonico = json.dumps(
        {
            "usuario_id": usuario_id,
            # Ordenado por SKU: dois pedidos idênticos escritos em ordens
            # diferentes precisam gerar a mesma chave.
            "itens": sorted(
                (
                    {
                        "sku": item["sku"],
                        "quantidade": item["quantidade"],
                        "preco_unitario": item["preco_unitario"],
                    }
                    for item in itens
                ),
                key=lambda item: item["sku"],
            ),
            "total": f"{total:.2f}",
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(canonico.encode("utf-8")).hexdigest()


def _chave_pagamento(pedido_id: int, metodo: str, aprovado: bool) -> str:
    """Resolve a chave de idempotência do pagamento (64 hex, sha256).

    O header `Idempotency-Key` **não** entra aqui, e a diferença em relação ao
    pedido é deliberada: um pagamento é uma tentativa específica de
    (pedido, método, desfecho). Reenviar o mesmo POST precisa ser reconhecido
    como repetição — mas o header do cliente não sabe o desfecho que o gateway
    vai devolver, então usá-lo faria a chave depender de algo que o próprio POST
    ainda não decidiu. A chave vem do servidor, do conteúdo da tentativa.

    `canal_notificacao` fica de fora de propósito: notificar por SMS e por e-mail
    é a **mesma** cobrança, e o canal é escolha de entrega, não identidade do
    fato. Incluí-lo faria um re-POST com canal diferente parecer um pagamento
    diferente.
    """
    canonico = json.dumps(
        {
            "pedido_id": pedido_id,
            "metodo": metodo,
            "aprovado": bool(aprovado),
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(canonico.encode("utf-8")).hexdigest()


class PedidoViewSet(viewsets.ModelViewSet):
    """Pedidos: o POST publica `PedidoCriado`; o worker avança o estado.

    Matriz de permissões (diferente da do catálogo, e por um motivo de
    domínio):

    | Verbo           | Anônimo | user  | admin            |
    | --------------- | ------- | ----- | ---------------- |
    | POST            | ❌ 401  | ✅    | ✅               |
    | GET lista/detalhe| ❌ 401  | só o próprio | todos os pedidos |

    Pedido não é dado público como o catálogo: um usuário autenticado só
    enxerga os seus, e o papel `admin` enxerga todos (é quem precisa
    diagnosticar um pedido preso na DLQ).
    """

    queryset = Pedido.objects.select_related("usuario").order_by("-created_at")
    serializer_class = PedidoSerializer
    http_method_names = ["get", "post", "head", "options"]
    search_fields = ["status", "idempotency_key"]
    ordering_fields = ["created_at", "-created_at", "total", "status"]

    def get_permissions(self):
        if self.action == "create":
            return [permissions.IsAuthenticated()]
        # Leitura exige autenticação (a queryset já filtra por dono).
        return [permissions.IsAuthenticated()]

    def get_queryset(self):
        """Restringe a leitura ao dono; `admin` vê todos."""
        usuario = self.request.user
        if usuario.is_authenticated and usuario.groups.filter(name="admin").exists():
            return super().get_queryset()
        return super().get_queryset().filter(usuario=usuario)

    def create(self, request, *args, **kwargs):
        """Cria o pedido e publica o evento `PedidoCriado`.

        Sequência, e por que nesta ordem:

        1. valida o corpo e lê os preços no catálogo (o total nunca vem do
           cliente);
        2. grava o pedido em `pendente_publicacao` dentro de uma transação;
        3. publica o evento **depois** do commit (`transaction.on_commit`),
           para que um rollback não deixe evento de um pedido que não existe;
        4. marca o pedido como `pendente` e devolve 201 **com os dados da
           publicação** (id do evento, fila, instante) para que o cliente
           correlacione a resposta com o log do worker.

        Se o broker estiver fora, o passo 3 falha: a API responde **503** e o
        pedido permanece em `pendente_publicacao`, recuperável por
        `republicar_pedidos`. Responder 201 sem evento seria mentir para o
        cliente (e foi uma decisão consciente, não um esquecimento).
        """
        serializer = PedidoCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        itens_validados = serializer.validated_data["itens"]

        itens, total = self._resolver_itens(itens_validados)
        simular_falha = self._simular_falha(request)
        chave = _chave_idempotencia(request, itens, request.user.id, total)

        try:
            with transaction.atomic():
                pedido = Pedido.objects.create(
                    usuario=request.user,
                    status=settings.PEDIDO_ESTADO_INICIAL,
                    itens=itens,
                    total=total,
                    idempotency_key=chave,
                    simular_falha=simular_falha,
                )
        except IntegrityError:
            # A chave já existe: é a **idempotência no lado da requisição**
            # (o cliente reenviou o mesmo POST, ou o gateway repetiu). O
            # `unique=True` do banco é a autoridade; a exception só é a
            # newsgraça. O efeito sobre a fila é zero: o pedido já publicado
            # não publica de novo.
            return self._resposta_idempotente(chave, itens, total)

        # O publicador roda fora da transação: se ele subisse dentro dela e o
        # commit falhasse, teríamos um evento sem pedido. `on_commit` garante
        # a ordem certa.
        #
        # O publicador é chamado por um callable e o resultado volta por
        # "caixa de saída" (dict/list) em vez de exceção: se a exceção subisse
        # daqui, o Django a trataria como erro de request **depois** do
        # commit — o pedido existiria e o cliente receberia um 500 sem
        # explicação.
        publicacao: dict[str, Any] = {}
        erro: list[str] = []
        transaction.on_commit(lambda: self._publicar(pedido, chave, publicacao, erro))

        if not publicacao:
            return Response(
                {
                    "detail": (
                        "Pedido criado, mas o evento não pôde ser publicado "
                        "(broker indisponível). O pedido ficou com status "
                        f"'{settings.PEDIDO_ESTADO_INICIAL}' e pode ser "
                        "republicado com `manage.py republicar_pedidos`."
                    ),
                    "pedido_id": pedido.pk,
                    "status": settings.PEDIDO_ESTADO_INICIAL,
                    "idempotency_key": pedido.idempotency_key,
                    "erro": erro[0] if erro else "publicação não confirmada",
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        pedido.refresh_from_db()
        corpo = PedidoSerializer(pedido).data
        corpo["evento"] = publicacao
        return Response(corpo, status=status.HTTP_201_CREATED)

    # ------------------------------------------------------------------
    # Helpers do POST
    # ------------------------------------------------------------------
    @staticmethod
    def _resposta_idempotente(chave: str, itens: list[dict], total: Decimal) -> Response:
        """Responde a um POST repetido com a MESMA chave de idempotência.

        Duas situações, e a distinção importa:

        * mesma chave e **mesmo pedido** → devolve **200** com o pedido já
          existente. É o que o cliente quer: a resposta original, sem um
          segundo pedido e sem um segundo evento;
        * mesma chave e **pedido diferente** → **409**. Reaproveitar a chave
          para outro pedido é um erro do cliente (quase sempre um bug de
          cache de chave), e "aceitar" esconderia um pedido perdido.
        """
        existente = Pedido.objects.filter(idempotency_key=chave).first()
        if existente is None:  # pragma: no cover - corrida improvável
            raise Http404("Chave de idempotência em conflito, mas o pedido sumiu.")
        if existente.total != total or existente.itens != itens:
            return Response(
                {
                    "detail": (
                        "A Idempotency-Key já foi usada para outro pedido. "
                        "Gere uma chave nova para um pedido diferente."
                    ),
                    "idempotency_key": chave,
                    "pedido_id": existente.pk,
                },
                status=status.HTTP_409_CONFLICT,
            )
        corpo = PedidoSerializer(existente).data
        corpo["evento"] = {"duplicado": True, "motivo": "pedido já existente"}
        return Response(corpo, status=status.HTTP_200_OK)

    @staticmethod
    def _publicar(pedido: Pedido, chave: str, publicacao: dict, erro: list) -> None:
        """Publica o evento e registra o desfecho em `publicacao`/`erro`."""
        try:
            publicacao.update(mensageria.publicar_pedido_criado(pedido, chave))
        except mensageria.PublicacaoFalhou as excecao:
            erro.append(str(excecao))
            return
        # Só depois do publisher confirm o pedido pode ir para `pendente`.
        #
        # O filtro por `status` é obrigatório, e não um detalhe: entre o
        # `basic_publish` e esta linha o worker pode já ter consumido a
        # mensagem (medido: ~17 ms) e movido o pedido para `processado`. Um
        # `update` sem condição escreveria `pendente` por cima e o GET
        # mostraria um pedido processado como pendente — para sempre, porque
        # nada mais muda esse status.
        Pedido.objects.filter(
            pk=pedido.pk, status=settings.PEDIDO_ESTADO_INICIAL
        ).update(status=settings.PEDIDO_ESTADO_PUBLICADO)

    @staticmethod
    def _resolver_itens(itens: list[dict]) -> tuple[list[dict], Decimal]:
        """Lê os preços no catálogo e devolve `(itens_normalizados, total)`.

        404 se algum SKU não existir ou estiver inativo: um pedido não pode
        ser criado para um produto que saiu do catálogo, e a falha tem que
        aparecer no POST — não três segundos depois, quando o worker não
        conseguir ler o preço.
        """
        skus = [item["sku"] for item in itens]
        catalogo = {
            produto.sku: produto
            for produto in Item.objects.filter(sku__in=skus, is_active=True)
        }
        faltando = [sku for sku in skus if sku not in catalogo]
        if faltando:
            raise NotFound(
                f"SKU inexistente ou inativo no catálogo: {', '.join(faltando)}."
            )

        normalizados: list[dict] = []
        total = Decimal("0")
        for item in itens:
            produto = catalogo[item["sku"]]
            preco = produto.price
            normalizados.append(
                {
                    "sku": produto.sku,
                    "quantidade": item["quantidade"],
                    # Snapshot: o preço do momento da compra, guardado em
                    # string para não perder precisão em JSON.
                    "preco_unitario": f"{preco:.2f}",
                    "produto_id": produto.pk,
                }
            )
            total += preco * item["quantidade"]
        return normalizados, total.quantize(Decimal("0.01"))

    @staticmethod
    def _simular_falha(request) -> bool:
        """Header `X-Simular-Falha` (só se `PEDIDO_PERMITIR_SIMULACAO_FALHA`).

        É o gancho que valida a DLQ ponta a ponta: marca um pedido para o
        worker falhar de propósito, esgota a escada de reentrega e mostra a
        mensagem parada na DLQ. Fora de desenvolvimento, o header é ignorado
        — um cliente não deve poder sabotar o próprio pedido.
        """
        if not settings.PEDIDO_PERMITIR_SIMULACAO_FALHA:
            return False
        return request.headers.get("X-Simular-Falha", "").strip().lower() in {
            "1",
            "true",
            "sim",
            "yes",
        }

    # ------------------------------------------------------------------
    # Aula 11 — `POST /pedidos/{id}/pagamento/`: o produtor do
    # `PagamentoRegistrado`
    # ------------------------------------------------------------------
    @action(detail=True, methods=["get", "post"], url_path="pagamento")
    def pagamento(self, request, pk: str | None = None) -> Response:
        """Simula o gateway, grava o `Pagamento` e publica o evento.

        O gateway é simulado porque a aula precisa do **fluxo**, não de um
        provedor real: o POST decide o desfecho (`aprovado`/`recusado`) e o
        worker reage a ele. O que importa é que a decisão do "gateway" e a
        publicação do evento sejam passos separados, como seriam no mundo real.

        Sequência (a mesma ordem do `create`, pelas mesmas razões):

        1. valida o corpo e a existência do pedido (404 se não houver);
        2. grava o `Pagamento` em `registrado` numa transação;
        3. publica o `PagamentoRegistrado` **depois** do commit;
        4. devolve 201 com os dados da publicação.

        O passo 3 falhando deixa o pagamento em `registrado` e a resposta é
        **503** — e o re-POST no mesmo endpoint republica (é o que o
        idempotency_key do pagamento permite ver, abaixo). Não há
        `pending_publicacao` aqui: `registrado` já é esse estado.

        `GET` no mesmo caminho devolve o pagamento atual, o que dá ao cliente
        o polling do desfecho sem precisar do recurso de notificação.
        """
        pedido = self.get_object()
        simular_falha = self._simular_falha_pagamento(request)

        if request.method == "GET":
            pagamento = (
                Pagamento.objects.filter(pedido=pedido)
                .select_related("pedido__usuario")
                .first()
            )
            if pagamento is None:
                return Response(
                    {
                        "detail": "Este pedido ainda não tem pagamento registrado.",
                        "pedido_id": pedido.pk,
                    },
                    status=status.HTTP_404_NOT_FOUND,
                )
            return Response(PagamentoSerializer(pagamento).data)

        serializer = PagamentoSimularSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        dados = serializer.validated_data

        # A chave de idempotência é do servidor, derivada de
        # (pedido, metodo, desfecho). Um pagamento é uma tentativa **específica**:
        # re-POSTar com outro método ou outro desfecho é outra tentativa, não a
        # repetição da anterior. Como `Pagamento.pedido` é `OneToOne`, a
        # segunda tentativa cai no `IntegrityError` e é tratada abaixo — e a
        # chave é o que separa os dois casos ali (ver `_republicar_pagamento`).
        chave = _chave_pagamento(
            pedido.pk, dados["metodo"], bool(dados["aprovado"])
        )

        try:
            with transaction.atomic():
                pagamento = Pagamento.objects.create(
                    pedido=pedido,
                    metodo=dados["metodo"],
                    # Snapshot de `Pedido.total`: o catálogo pode mudar depois, e
                    # a cobrança não pode.
                    valor=pedido.total,
                    transacao_id=f"txn-{uuid.uuid4().hex[:24]}",
                    aprovado=dados["aprovado"],
                    motivo_recusa=dados.get("motivo_recusa") or "",
                    status=Pagamento.REGISTRADO,
                    idempotency_key=chave,
                    simular_falha=simular_falha,
                )
        except IntegrityError:
            return self._republicar_pagamento(
                pedido, chave, dados.get("canal") or ""
            )

        # `canal_notificacao` é atributo efêmero: o contrato o lê, mas não é
        # coluna do `Pagamento` (quem o persiste é a `Notificacao`, criada pelo
        # worker). Atribuir aqui, e não no `create`, deixa explícito que ele
        # existe só entre a publicação e o worker.
        pagamento.canal_notificacao = dados.get("canal") or Notificacao.CANAL_EMAIL

        publicacao: dict[str, Any] = {}
        erro: list[str] = []
        transaction.on_commit(lambda: self._publicar_pagamento(pagamento, publicacao, erro))

        if not publicacao:
            return Response(
                {
                    "detail": (
                        "Pagamento registrado, mas o evento não pôde ser "
                        "publicado (broker indisponível). O pagamento ficou com "
                        f"status '{Pagamento.REGISTRADO}' e o mesmo POST "
                        "republica o evento."
                    ),
                    "pagamento_id": pagamento.pk,
                    "pedido_id": pedido.pk,
                    "status": Pagamento.REGISTRADO,
                    "idempotency_key": pagamento.idempotency_key,
                    "erro": erro[0] if erro else "publicação não confirmada",
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        pagamento.refresh_from_db()
        # O bloco `evento` (tópico, partição, offset, `evento_id`) é o que liga
        # a resposta ao log do worker, e é o mesmo que o re-POST devolve. Sem
        # ele aqui, o cliente teria o pagamento mas não a prova de onde ele
        # foi parar - e o `PedidoCriado` já devolve esses dados no 201.
        return Response(
            {
                **PagamentoSerializer(pagamento).data,
                "evento": publicacao,
            },
            status=status.HTTP_201_CREATED,
        )

    @staticmethod
    def _publicar_pagamento(
        pagamento: Pagamento, publicacao: dict, erro: list
    ) -> None:
        """Publica o `PagamentoRegistrado` e registra o desfecho nas caixas.

        Diferente do pedido, **não** há update de status depois da publicação:
        `registrado` → `aprovado`/`recusado` é o **worker** que faz, no efeito do
        evento. Se a API fizesse esse update, o worker's `UPDATE` condicional
        (que só avança a partir de `registrado`) casaria zero linhas e a
        notificação — o efeito que importa — nunca seria criada.
        """
        try:
            publicacao.update(
                mensageria.publicar_pagamento_registrado(pagamento)
            )
        except mensageria.PublicacaoFalhou as excecao:
            erro.append(str(excecao))

    def _republicar_pagamento(
        self, pedido: Pedido, chave: str, canal: str
    ) -> Response:
        """Trata o re-POST depois do `IntegrityError` do `OneToOne`.

        O `IntegrityError` só diz que **este pedido já tem um pagamento** — não
        que ele é o pagamento que o cliente está tentando criar. A distinção é
        feita pela `idempotency_key`, que é derivada de
        (pedido, método, desfecho):

        * chave **igual** → é a mesma tentativa. republica se ainda estiver em
          `registrado` (a recuperação do 503) e devolve 200; se já resolvido,
          devolve 200 com o estado atual e `republicado: false`, porque o
          gateway já respondeu e publicar de novo notificaria um fato já
          notificado;
        * chave **diferente** → é outra tentativa (outro método ou outro
          desfecho), e `OneToOne` a impede. Devolve **409** com o pagamento
          existente no corpo.

        Sem essa checagem, um POST com `metodo=boleto` contra um pedido pago com
        PIX devolvia 200 e o pagamento em PIX — o cliente receberia um
        "deu certo" para um pedido que não tentou fazer. Um 409 é a resposta
        honesta: a linha existe e não é a que você pediu.
        """
        pagamento = (
            Pagamento.objects.filter(pedido=pedido)
            .select_related("pedido__usuario")
            .first()
        )
        if pagamento is None:  # pragma: no cover - corrida improvável
            raise Http404("Pagamento em conflito, mas sumiu do banco.")

        if pagamento.idempotency_key != chave:
            return Response(
                {
                    "detail": (
                        "Este pedido já tem um pagamento registrado, e o método "
                        "ou desfecho enviado é diferente do pagamento existente. "
                        "Um pedido aceita um único pagamento (OneToOne); para "
                        "tentar de novo é preciso um novo pedido."
                    ),
                    "pedido_id": pedido.pk,
                    "pagamento_existente": PagamentoSerializer(pagamento).data,
                    "idempotency_key_enviado": chave,
                    "idempotency_key_existente": pagamento.idempotency_key,
                },
                status=status.HTTP_409_CONFLICT,
            )

        if pagamento.status == Pagamento.REGISTRADO:
            # O canal **não** é persistido no `Pagamento`, então a republicação
            # usa o canal desta requisição em vez de um default fixo: se o
            # cliente pediu `sms` e o primeiro POST só falhou na publicação,
            # forçar `email` aqui entregaria o aviso no canal que ele não pediu.
            pagamento.canal_notificacao = (
                canal or Notificacao.CANAL_EMAIL
            )
            publicacao: dict[str, Any] = {}
            erro: list[str] = []
            self._publicar_pagamento(pagamento, publicacao, erro)
            if not publicacao:
                return Response(
                    {
                        "detail": (
                            "Pagamento continua em 'registrado' e o evento não "
                            "pôde ser publicado (broker indisponível)."
                        ),
                        "pagamento_id": pagamento.pk,
                        "status": pagamento.status,
                        "erro": erro[0] if erro else "publicação não confirmada",
                    },
                    status=status.HTTP_503_SERVICE_UNAVAILABLE,
                )
            return Response(
                {
                    **PagamentoSerializer(pagamento).data,
                    "evento": publicacao,
                    "republicado": True,
                },
                status=status.HTTP_200_OK,
            )

        return Response(
            {
                **PagamentoSerializer(pagamento).data,
                "evento": {
                    "duplicado": True,
                    "motivo": (
                        f"o pagamento já estava resolvido ('{pagamento.status}')"
                    ),
                },
                "republicado": False,
            },
            status=status.HTTP_200_OK,
        )

    @staticmethod
    def _simular_falha_pagamento(request) -> bool:
        """Como `_simular_falha`, mas para o fluxo de pagamento.

        O interruptor é separado (`PAGAMENTO_PERMITIR_SIMULACAO_FALHA`) e é
        consultado **aqui**, na API, exatamente como no fluxo de pedidos: o
        worker não lê flag nenhuma, ele honra `simular_falha` gravado no banco.
        A marcação é o que faz a mensagem escalar; a flag é o que decide se o
        cliente pode pedir isso.

        Separar os dois interruptores (e não um só) porque a falha injetada
        manda a mensagem para a DLQ **do fluxo de pagamento** - misturar as duas
        sabotagens no mesmo ambiente tornaria "qual fluxo parou?" mais difícil de
        responder do que precisava.
        """
        if not settings.PAGAMENTO_PERMITIR_SIMULACAO_FALHA:
            return False
        return request.headers.get("X-Simular-Falha", "").strip().lower() in {
            "1",
            "true",
            "sim",
            "yes",
        }


class NotificacaoViewSet(viewsets.ReadOnlyModelViewSet):
    """`GET /api/v1/notificacoes/` — o que o cliente foi avisado.

    Mesma matriz do pedido, e pela mesma razão de domínio: notificação é dado
    **pessoal**. O usuário enxerga as suas; `admin` enxerga todas (é quem
    investiga um aviso que não saiu).

    A queryset já vem filtrada e com `select_related("pagamento")`: o serializer
    precisa do `pagamento_id`, e sem o join seria uma query por linha numa
    listagem.
    """

    queryset = Notificacao.objects.select_related(
        "pagamento", "pedido__usuario"
    ).order_by("-enviada_em")
    serializer_class = NotificacaoSerializer
    http_method_names = ["get", "head", "options"]
    # `search` e `ordering` já são globais (settings); falta declarar aqui o que
    # esta listagem **aceita como filtro**, que é a única decisão local.
    #
    # `pedido` e `canal` são os dois eixos que fazem sentido para quem lê um
    # aviso: "o que foi avisado sobre este pedido" e " quantos e-mails saíram".
    # Sem esta linha, `?pedido=5111` era **ignorado em silêncio** e a resposta
    # trazia a lista inteira — o filtro parece funcionar e mente, que é pior do
    # que recusar.
    filterset_fields = ["pedido", "canal"]
    search_fields = ["canal", "titulo"]
    ordering_fields = ["enviada_em", "-enviada_em"]

    def get_permissions(self):
        return [permissions.IsAuthenticated()]

    def get_queryset(self):
        usuario = self.request.user
        if usuario.is_authenticated and usuario.groups.filter(name="admin").exists():
            return super().get_queryset()
        return super().get_queryset().filter(pedido__usuario=usuario)


class CacheMetricsView(APIView):
    """`GET /api/v1/cache/metrics/` — eficácia do cache (exposta por endpoint).

    A spec da Aula 8 pede a métrica de hit rate (`total_hits/total_lookups`)
    "por endpoint"; aqui ela vem por *namespace* de cache, que corresponde
    1:1 aos endpoints instrumentados (ver `core/cache.py`).

    Restrita ao papel `admin` (mesma classe `IsAdminRole` da Aula 7): expõe
    informação operacional da aplicação. A URL do Redis sai com a credencial
    redigida, mesmo para o admin.
    """

    permission_classes = [IsAdminRole]

    def get(self, request) -> Response:
        namespaces = {
            namespace: contadores.as_dict()
            for namespace, contadores in sorted(cache_metrics.snapshot().items())
        }
        return Response(
            {
                "cache_habilitado": cache_api.cache_habilitado(),
                "redis": {
                    "url": cache_api.redis_url_publicavel(),
                    "key_prefix": self._key_prefix(),
                    "ttl_lista_s": cache_api.ttl_listagem(),
                    "ttl_detalhe_s": cache_api.ttl_detalhe(),
                },
                "total": cache_metrics.total().as_dict(),
                "namespaces": namespaces,
            }
        )

    def _key_prefix(self) -> str:
        return settings.CACHES["default"].get("KEY_PREFIX", "")


# =====================================================================
# Aula 14 — Assistente de IA (`POST /api/v1/assist`)
# =====================================================================
# As instruções de sistema por modo são o "template de prompt" da iteração:
# `summarize` pede o resumo operacional; `explain` pede a explicação com causa
# provável e próximo passo. O provedor de hoje é o mock (devolve o texto em
# eco); o template é o mesmo que o provedor real receberá.
MODO_ASSIST = {
    "summarize": (
        "Você é um assistente de operações. Resuma os logs a seguir de forma "
        "objetiva, destacando erros, anomalias e o que exige atenção."
    ),
    "explain": (
        "Você é um assistente de operações. Explique o que os logs a seguir "
        "indicam, incluindo a causa provável e o próximo passo recomendado."
    ),
}


class AssistView(APIView):
    """`POST /api/v1/assist` — sumariza ou explica logs via `llm_service`.

    Exige autenticação (JWT): é uma operação que consome tokens do provedor e
    recebe logs que podem conter dados sensíveis — o mesmo motivo pelo qual
    pedidos e pagamentos não são públicos. O throttling `user` (100/min, global
    no DRF) já atua como cota de custo por usuário.

    A view é fina de propósito: valida a entrada, delega ao `llm_service` (que
    concentra timeout, retry e circuit breaker) e traduz o desfecho para HTTP.
    O `LlmTerminal` (ex.: resposta malformada do provedor) vira **502** — a
    culpa não é do cliente; `CircuitoAberto`/`LlmIndisponivel` viram **503**
    (tente de novo mais tarde); configuração inválida vira **500**.
    """

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request) -> Response:
        serializer = AssistSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        dados = serializer.validated_data

        try:
            servico = criar_llm_service()
            resposta = servico.completar(
                self._mensagens(dados["mode"], dados["logs"]),
                temperature=dados["temperature"],
                max_tokens=dados["max_tokens"],
            )
        except LlmConfiguracaoInvalida as falha:
            logger.error(
                "llm_service mal configurado",
                extra={
                    "evento": "AssistConfiguracaoInvalida",
                    "resultado": "erro",
                    "erro": str(falha),
                },
            )
            return Response(
                {"detail": "A camada de IA está mal configurada no servidor."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        except (CircuitoAberto, LlmIndisponivel) as falha:
            logger.warning(
                "provedor de IA indisponível",
                extra={
                    "evento": "AssistIndisponivel",
                    "resultado": "erro",
                    "erro": str(falha),
                },
            )
            return Response(
                {
                    "detail": (
                        "O provedor de IA está indisponível no momento. "
                        "Tente novamente mais tarde."
                    )
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        except LlmTerminal as falha:
            logger.warning(
                "provedor de IA devolveu resposta inválida",
                extra={
                    "evento": "AssistTerminal",
                    "resultado": "erro",
                    "erro": str(falha),
                },
            )
            return Response(
                {"detail": "O provedor de IA devolveu uma resposta inválida."},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        # Contrato do DoD: a resposta gerada e os metadados de consumo de tokens.
        return Response(
            {
                "answer": resposta.texto,
                "meta": {
                    "tokens_prompt": resposta.tokens_prompt,
                    "tokens_output": resposta.tokens_output,
                },
            }
        )

    @staticmethod
    def _mensagens(mode: str, logs: list[str]) -> list[dict[str, str]]:
        """Monta a conversa (system + user) que vai para o provedor."""
        return [
            {"role": "system", "content": MODO_ASSIST[mode]},
            {"role": "user", "content": "\n".join(logs)},
        ]


class LlmMetricsView(APIView):
    """`GET /api/v1/llm/metrics/` — telemetria do `llm_service` (Aula 14).

    Expõe os contadores do processo: desfechos (sucesso/falha/terminal), as
    chamadas bloqueadas pelo circuit breaker, tokens consumidos, custo estimado
    e latência média — além da configuração efetiva (provedor, modelo, timeout,
    preços por 1M de tokens) para que o operador saiba com que base os números
    foram calculados.

    Restrita ao papel `admin` (`IsAdminRole`, como o `/cache/metrics/`): é
    informação operacional e de custo. Limite conhecido: são contadores do
    processo que atende a requisição (ver docstring de `core/llm/metricas.py`).
    """

    permission_classes = [IsAdminRole]

    def get(self, request) -> Response:
        return Response(
            {
                "provedor": getattr(settings, "LLM_PROVIDER", "mock"),
                "modelo": getattr(settings, "LLM_MODEL", "mock"),
                "timeout_segundos": getattr(settings, "LLM_TIMEOUT_SEGUNDOS", 5.0),
                "redacao_ativa": getattr(settings, "LLM_REDACAO_ATIVA", True),
                "custo_por_1m_tokens": {
                    "input_usd": getattr(settings, "LLM_CUSTO_INPUT_POR_1M_TOKENS", 0.0),
                    "output_usd": getattr(
                        settings, "LLM_CUSTO_OUTPUT_POR_1M_TOKENS", 0.0
                    ),
                },
                "total": llm_metrics.snapshot(),
            }
        )
