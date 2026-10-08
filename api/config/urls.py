from django.contrib import admin
from django.urls import include, path

from core.views import health
from core.wiki_docs import doc_openapi_yaml, redoc, swagger_ui

urlpatterns = [
    path("admin/", admin.site.urls),
    path("health", health, name="health"),
    path("api/v1/", include("core.urls")),
    # Aula 13 — documentação interativa (DoD 4): o contrato e as UIs.
    path("docs/openapi.yaml", doc_openapi_yaml, name="openapi-contrato"),
    path("docs/", swagger_ui, name="swagger-ui"),
    path("redoc/", redoc, name="redoc"),
]