from django.db.models import Count
from django.http import JsonResponse
from rest_framework import permissions, viewsets

from .filters import ItemFilter
from .models import Category, Item
from .permissions import IsAdminRole
from .serializers import CategorySerializer, ItemSerializer


def health(request):
    return JsonResponse({"status": "ok", "service": "synapseshop-api"})


# Matriz de permissões da Aula 7 (aplicada a Category e Item):
#   - GET list/detail  -> público (AllowAny): catálogo de leitura livre.
#   - POST             -> qualquer usuário autenticado (papel user ou admin).
#   - PUT/PATCH/DELETE -> exclusivos do papel admin (rotas administrativas).
# A implementação usa `get_permissions()`, que devolve permissões diferentes
# por ação — é o ponto do DRF onde cada verbo HTTP recebe sua regra.


class CategoryViewSet(viewsets.ModelViewSet):
    """CRUD de categorias com permissões por ação e busca no Admin."""

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


class ItemViewSet(viewsets.ModelViewSet):
    """CRUD de produtos com paginação + filtros coerentes (Aula 7)."""

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
