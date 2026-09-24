import django_filters

from .models import Item


class ItemFilter(django_filters.FilterSet):
    """
    FilterSet declarativo do Item (Aula 7). Expõe filtros de domínio
    coerentes para a listagem pública do catálogo:

      ?category=<id>     categoria exata (id numérico; inexistente => vazio)
      ?is_active=true    apenas produtos ativos
      ?min_price=1000    preço >= 1000
      ?max_price=5000    preço <= 5000

    `category` usa NumberFilter sobre `category_id` de propósito: em vez de
    falhar com 400 ao receber um id de categoria inexistente (comportamento
    padrão do ModelChoiceFilter), a listagem simplesmente retorna vazia —
    mais amigável para um catálogo público.

    A busca livre (?search=) e a ordenação (?ordering=) ficam no viewset
    via SearchFilter/OrderingFilter do DRF — ver core/views.py.
    """

    category = django_filters.NumberFilter(
        field_name="category_id",
        label="categoria (id)",
    )
    min_price = django_filters.NumberFilter(
        field_name="price",
        lookup_expr="gte",
        label="preço mínimo",
    )
    max_price = django_filters.NumberFilter(
        field_name="price",
        lookup_expr="lte",
        label="preço máximo",
    )

    class Meta:
        model = Item
        fields = ["is_active"]
