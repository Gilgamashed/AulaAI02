from django.db.models import Count
from django.http import JsonResponse
from rest_framework import viewsets

from .models import Category, Item
from .serializers import CategorySerializer, ItemSerializer


def health(request):
    return JsonResponse({"status": "ok", "service": "synapseshop-api"})


class CategoryViewSet(viewsets.ModelViewSet):
    queryset = Category.objects.annotate(items_count=Count("items")).order_by("name")
    serializer_class = CategorySerializer


class ItemViewSet(viewsets.ModelViewSet):
    queryset = Item.objects.select_related("category").order_by("-created_at")
    serializer_class = ItemSerializer