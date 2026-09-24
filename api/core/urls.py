from django.urls import path
from rest_framework.routers import DefaultRouter
from rest_framework.throttling import ScopedRateThrottle
from rest_framework_simplejwt.views import (
    TokenObtainPairView,
    TokenRefreshView,
    TokenVerifyView,
)

from .views import CategoryViewSet, ItemViewSet


class LoginThrottledTokenObtainPairView(TokenObtainPairView):
    """
    POST /api/v1/auth/token/ — emite o par access/refresh (login).
    Herda do SimpleJWT e adiciona o ScopedRateThrottle com scope "login"
    (5 tentativas/minuto, configurado em settings.py) para conter força bruta.
    """

    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "login"


class LoginThrottledTokenRefreshView(TokenRefreshView):
    """
    POST /api/v1/auth/token/refresh/ — troca o refresh por um novo access.
    Também entra na cota de "login", pois é uma operação autenticante.
    """

    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "login"


router = DefaultRouter()
router.register("categories", CategoryViewSet, basename="category")
router.register("items", ItemViewSet, basename="item")

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
] + router.urls
