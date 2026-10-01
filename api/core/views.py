import hashlib
import json
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
from .messaging import produtor
from .models import Category, Item, Pedido
from .permissions import IsAdminRole
from .serializers import (
    CategorySerializer,
    ItemDetalheSerializer,
    ItemSerializer,
    PedidoCreateSerializer,
    PedidoSerializer,
)


def health(request):
    return JsonResponse({"status": "ok", "service": "synapseshop-api"})


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
            publicacao.update(produtor.publicar_pedido_criado(pedido, chave))
        except produtor.PublicacaoFalhou as excecao:
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
