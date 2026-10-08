"""Rotas de documentação interativa da API (Aula 13, DoD 4).

Serve o contrato OpenAPI auditado (`docs/openapi.yaml`) e as duas interfaces
interativas: **Swagger UI** e **ReDoc**. A UI usa os bundles oficiais a partir
do CDN jsdelivr e aponta sempre para o ficheiro de contrato — é ele, e não um
schema gerado em runtime, que carrega as convenções documentadas nos
DoDs 1–3 (paginação `page/limit/nextCursor`, `sort=<campo>:<dir>`,
`X-Trace-Id`, erros `application/problem+json`).

O ficheiro de contrato já vive dentro da imagem: o `Dockerfile` copia o
contexto de build para `/app` e o `.dockerignore` não exclui `docs/`, então
`BASE_DIR.parent / "docs" / "openapi.yaml"` resolve em runtime e em teste
(roda na raiz do repositório).
"""

from functools import lru_cache

from django.conf import settings
from django.http import HttpResponse
from django.views.decorators.http import require_GET

CONTRATO_CONTENT_TYPE = "application/yaml; charset=utf-8"


def _caminho_contrato():
    # BASE_DIR é `<raiz do repositório>/api`; o contrato fica ao lado dele.
    return settings.BASE_DIR.parent / "docs" / "openapi.yaml"


@lru_cache(maxsize=1)
def _conteudo_contrato() -> str:
    """Lê o contrato uma vez por processo (o ficheiro só muda em build)."""
    return _caminho_contrato().read_text(encoding="utf-8")


@require_GET
def doc_openapi_yaml(request):
    """Devolve o contrato `docs/openapi.yaml` usado pelas duas interfaces."""
    return HttpResponse(_conteudo_contrato(), content_type=CONTRATO_CONTENT_TYPE)


@require_GET
def swagger_ui(request):
    """Swagger UI carregando o contrato servido em `/docs/openapi.yaml`."""
    html = """\
<!DOCTYPE html>
<html lang="pt-br">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>SynapseShop — Swagger UI</title>
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui.css">
</head>
<body>
  <div id="swagger-ui"></div>
  <script src="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
  <script>
    window.onload = function () {
      window.ui = SwaggerUIBundle({
        url: "/docs/openapi.yaml",
        dom_id: "#swagger-ui",
        deepLinking: true,
        persistAuthorization: true,
        displayRequestDuration: true,
        docExpansion: "list",
      });
    };
  </script>
</body>
</html>
"""
    return HttpResponse(html, content_type="text/html; charset=utf-8")


@require_GET
def redoc(request):
    """ReDoc carregando o contrato servido em `/docs/openapi.yaml`."""
    html = """\
<!DOCTYPE html>
<html lang="pt-br">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>SynapseShop — ReDoc</title>
  <style>body { margin: 0; }</style>
</head>
<body>
  <redoc spec-url="/docs/openapi.yaml"></redoc>
  <script src="https://cdn.jsdelivr.net/npm/redoc@2/bundles/redoc.standalone.js"></script>
</body>
</html>
"""
    return HttpResponse(html, content_type="text/html; charset=utf-8")