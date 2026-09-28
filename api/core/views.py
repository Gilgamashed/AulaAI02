from typing import Any

from django.conf import settings
from django.db.models import Count
from django.http import JsonResponse
from rest_framework import permissions, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from . import cache as cache_api
from .cache_metrics import cache_metrics
from .filters import ItemFilter
from .models import Category, Item
from .permissions import IsAdminRole
from .serializers import (
    CategorySerializer,
    ItemDetalheSerializer,
    ItemSerializer,
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
