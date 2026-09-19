# ============================================================
# SynapseShop — Inventory Service (Dockerfile, multistage build)
# Requisitos do scaffold (Aula 5):
#   1. Imagem oficial do Python (python:3.12-slim)
#   2. Usuário não-root (menor privilégio)
#   3. Cache de camadas + cache mount do BuildKit
#   4. Runtime ASGI (uvicorn) na porta 8001 — a 8000 é do Django
# Build context: services/inventory (docker build services/inventory)
# ============================================================

# ====================================================================
# ESTÁGIO 1 — BUILDER
# Prepara apenas Python, pip e dependências; não entra na imagem final.
# ====================================================================
FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /build

# CACHE DE CAMADA — dependências ANTES do código (só invalidam com mudanças
# no requirements.txt). CACHE MOUNT reutiliza os downloads do pip entre builds.
COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --upgrade pip \
    && mkdir -p /install \
    && pip install --prefix=/install -r requirements.txt

# ====================================================================
# ESTÁGIO 2 — RUNTIME
# Imagem final enxuta: runtime ASGI (uvicorn) como usuário não-root.
# ====================================================================
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN useradd --create-home --shell /bin/bash appuser

# Copia apenas o que foi instalado no builder (sem toolchain de build).
COPY --from=builder /install /usr/local

# Código-fonte por último (preserva o cache das camadas anteriores).
COPY --chown=appuser:appuser app ./app

USER appuser

EXPOSE 8001

# Runtime ASGI na porta 8001.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]