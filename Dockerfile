# ============================================================
# SynapseShop — Dockerfile (multistage build)
# Requisitos atendidos:
#   1. Runtime correto (imagem oficial do Python)
#   2. Usuário não-root (menor privilégio)
#   3. Uso de cache (camada + cache mount do BuildKit)
#   4. Multistage build (specs_da_aula_3, item 4)
# ============================================================

# ====================================================================
# ESTÁGIO 1 — BUILDER
# Responsável apenas por preparar o Python, o pip e as dependências.
# Esse estágio é descartado no final: o runtime copia só o necessário.
# ====================================================================
FROM python:3.12-slim AS builder

# PYTHONDONTWRITEBYTECODE=1 : evita criar __pycache__/.pyc durante o install.
# PYTHONUNBUFFERED=1        : logs saem imediatamente no stdout.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /build

# --- CACHE DE CAMADA — dependências ANTES do código ------------------
# Copiamos apenas o requirements.txt. Assim, a camada de instalação só
# é reconstruída quando esse arquivo mudar (código novo não invalida).
COPY requirements.txt .

# --- CACHE MOUNT (BuildKit) ------------------------------------------
# O --mount=type=cache mantém o cache do pip fora da imagem, reutilizado
# entre builds. --prefix=/install grava as dependências num diretório
# próprio, que o estágio runtime vai copiar depois.
# O mkdir garante que /install exista mesmo com requirements.txt vazio.
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --upgrade pip \
    && mkdir -p /install \
    && pip install --prefix=/install -r requirements.txt

# ====================================================================
# ESTÁGIO 2 — RUNTIME
# Imagem final, enxuta: sem toolchain de build nem cache do pip.
# ====================================================================
FROM python:3.12-slim

# --- AMBIENTE PYTHON ------------------------------------------------
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# --- DIRETÓRIO DE TRABALHO ------------------------------------------
WORKDIR /app

# --- USUÁRIO NÃO-ROOT ------------------------------------------------
# Cria 'appuser' enquanto o build ainda roda como root. No runtime o
# processo roda como 'appuser' (USER ao final) — menor privilégio.
RUN useradd --create-home --shell /bin/bash appuser

# --- DEPENDÊNCIAS DO BUILDER -----------------------------------------
# Copia de /install (estágio 1) para /usr/local do runtime. Assim a
# imagem final não carrega toolchain de build nem o estágio builder.
COPY --from=builder /install /usr/local

# --- CÓDIGO FONTE — por último ----------------------------------------
# Copiado depois das dependências para preservar o cache das camadas
# anteriores. O estágio de build (builder) não é levado para a imagem.
COPY --chown=appuser:appuser . .

# --- EXECUÇÃO COMO NÃO-ROOT -------------------------------------------
USER appuser

# --- PORTA DOCUMENTADA ------------------------------------------------
# EXPOSE é informativo; o binding do host é feito no docker-compose.
EXPOSE 8000

# --- ENTRYPOINT DA API ------------------------------------------------
# Servidor HTTP (somente stdlib, sem framework nesta fase) com /health.
CMD ["python", "-u", "api/main.py"]