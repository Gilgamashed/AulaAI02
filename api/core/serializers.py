from django.db.models import Avg, Count, Max, Min
from rest_framework import serializers
from rest_framework.validators import UniqueValidator

from .models import Category, Item, validate_sku


def _strip_required(value, label):
    stripped = value.strip()
    if not stripped:
        raise serializers.ValidationError(f"O campo {label} não pode ser vazio.")
    return stripped


class CategorySerializer(serializers.ModelSerializer):
    items_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Category
        fields = [
            "id",
            "name",
            "slug",
            "description",
            "items_count",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "slug", "items_count", "created_at", "updated_at"]

    def validate_name(self, value):
        return _strip_required(value, "nome da categoria")


class ItemSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source="category.name", read_only=True)
    sku = serializers.CharField(
        max_length=100,
        validators=[
            UniqueValidator(
                queryset=Item.objects.all(),
                message="Já existe um produto com este SKU.",
            ),
            validate_sku,
        ],
    )

    class Meta:
        model = Item
        fields = [
            "id",
            "name",
            "brand",
            "model",
            "sku",
            "description",
            "price",
            "specifications",
            "warranty_months",
            "category",
            "category_name",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "category_name", "created_at", "updated_at"]

    def validate_name(self, value):
        return _strip_required(value, "nome")

    def validate_brand(self, value):
        return _strip_required(value, "marca")

    def validate_model(self, value):
        return _strip_required(value, "modelo")

    def validate_price(self, value):
        if value < 0:
            raise serializers.ValidationError("O preço não pode ser negativo.")
        return value

    def validate_specifications(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError(
                "As especificações devem ser um objeto JSON (dict)."
            )
        return value


class CategoryResumoSerializer(serializers.ModelSerializer):
    """Categoria enxuta para embutir em outros payloads.

    Não inclui `items_count` (que só existe quando a queryset é anotada com
    `Count("items")`, como na listagem de categorias): embutir a categoria em
    outro recurso exigiria garantir essa anotação em todas as consultas.
    """

    class Meta:
        model = Category
        fields = ["id", "name", "slug", "description", "created_at", "updated_at"]
        read_only_fields = fields


class ItemResumoSerializer(serializers.ModelSerializer):
    """Item enxuto para as listas de apoio (`mais_caros`, `recentes`)."""

    class Meta:
        model = Item
        fields = ["id", "name", "brand", "model", "sku", "price"]
        read_only_fields = fields


class ItemDetalheSerializer(serializers.ModelSerializer):
    """Consulta **pesada** de um produto (Aula 8) — fonte do cache `detalhes`.

    O `GET /api/v1/items/{id}/` sozinho é um `SELECT` por PK (o filtro de
    listagem não se aplica). Já o detalhe de negócio precisa cruzar a
    categoria do produto:

    * `SELECT` com `COUNT`/`AVG`/`MIN`/`MAX` sobre os itens da categoria;
    * até 3 itens mais caros da categoria (`ORDER BY price DESC LIMIT 3`);
    * até 3 itens mais recentes (`ORDER BY -created_at LIMIT 3`);
    * a categoria inteira (descrição, slug, datas).

    São 4 consultas por requisição — custo que o cache-aside reduz a um
    `GET` no Redis depois do primeiro acesso. As agregações ficam em
    `SerializerMethodField`: elas só são executadas no **MISS**, já que no
    HIT a resposta vem inteira do cache.
    """

    # `source="category"` é obrigatório: sem ele o DRF buscaria um atributo
    # chamado `categoria` no model (que não existe) e — em silêncio — pularia
    # o campo na resposta (SkipField), em vez de erro.
    categoria = CategoryResumoSerializer(source="category", read_only=True)
    estatisticas_categoria = serializers.SerializerMethodField()
    itens_mais_caros = serializers.SerializerMethodField()
    itens_recentes = serializers.SerializerMethodField()

    class Meta:
        model = Item
        fields = [
            "id",
            "name",
            "brand",
            "model",
            "sku",
            "description",
            "price",
            "specifications",
            "warranty_months",
            "category",
            "is_active",
            "created_at",
            "updated_at",
            "categoria",
            "estatisticas_categoria",
            "itens_mais_caros",
            "itens_recentes",
        ]
        read_only_fields = fields

    def get_estatisticas_categoria(self, obj: Item) -> dict:
        """Agregados da categoria do item (COUNT/AVG/MIN/MAX de preço)."""
        return obj.category.items.aggregate(
            total_itens=Count("id"),
            preco_medio=Avg("price"),
            preco_minimo=Min("price"),
            preco_maximo=Max("price"),
        )

    def get_itens_mais_caros(self, obj: Item) -> list:
        """Top 3 por preço dentro da mesma categoria do item."""
        return ItemResumoSerializer(
            obj.category.items.order_by("-price", "id")[:3], many=True
        ).data

    def get_itens_recentes(self, obj: Item) -> list:
        """Os 3 itens mais recentes da mesma categoria do item."""
        return ItemResumoSerializer(
            obj.category.items.order_by("-created_at", "id")[:3], many=True
        ).data