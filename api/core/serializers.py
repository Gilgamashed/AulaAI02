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