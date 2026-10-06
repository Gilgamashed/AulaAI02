from django.urls import path
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import (
    TokenObtainPairView,
    TokenRefreshView,
    TokenVerifyView,
)

from .throttling import ThrottleMemoriaScope
from .views import (
    CacheMetricsView,
    CategoryViewSet,
    ItemViewSet,
    NotificacaoViewSet,
    PedidoViewSet,
)


class LoginThrottledTokenObtainPairView(TokenObtainPairView):
    """
    POST /api/v1/auth/token/ — emite o par access/refresh (login).
    Herda do SimpleJWT e adiciona o ScopedRateThrottle com scope "login"
    (5 tentativas/minuto, configurado em settings.py) para conter força bruta.
    """

    throttle_classes = [ThrottleMemoriaScope]
    throttle_scope = "login"


class LoginThrottledTokenRefreshView(TokenRefreshView):
    """
    POST /api/v1/auth/token/refresh/ — troca o refresh por um novo access.
    Também entra na cota de "login", pois é uma operação autenticante.
    """

    throttle_classes = [ThrottleMemoriaScope]
    throttle_scope = "login"


router = DefaultRouter()
router.register("categories", CategoryViewSet, basename="category")
router.register("items", ItemViewSet, basename="item")
# Aula 9: o pedido é o produtor do evento `PedidoCriado`. Leitura (listagem e
# detalhe) exige autenticação e, fora do papel admin, só mostra os próprios
# pedidos — ver `PedidoViewSet.get_queryset`.
router.register("pedidos", PedidoViewSet, basename="pedido")

# Aula 11: as notificações que o `worker-pagamentos` criou. Recurso de **leitura
# só** (`ReadOnlyModelViewSet`): a notificação é efeito do evento, e nada na API
# a cria — criá-la aqui permitiria uma notificação sem pagamento, que é
# exatamente o que o `OneToOne` existe para impedir.
router.register("notificacoes", NotificacaoViewSet, basename="notificacao")

# Rotas de autenticação JWT (SimpleJWT) sob o prefixo /api/v1/auth/.
urlpatterns = [
    path(
        "auth/token/",
        LoginThrottledTokenObtainPairView.as_view(),
        name="token_obtain_pair",
    ),
    path(
        "auth/token/refresh/",
        LoginThrottledTokenRefreshView.as_view(),
        name="token_refresh",
    ),
    path("auth/token/verify/", TokenVerifyView.as_view(), name="token_verify"),
    # Aula 8: métricas de eficácia do cache (hit rate por namespace).
    # Restrito ao papel admin — ver CacheMetricsView.
    path(
        "cache/metrics/",
        CacheMetricsView.as_view(),
        name="cache-metrics",
    ),
] + router.urls
