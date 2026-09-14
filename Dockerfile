# ============================================================
# SynapseShop — Dockerfile
# Requisitos atendidos:
#   1. Runtime correto (imagem oficial do Python)
#   2. Usuário não-root (menor privilégio)
#   3. Uso de cache (camada + cache mount do BuildKit)
# ============================================================

# --- 1. RUNTIME -----------------------------------------------------
# Base oficial e enxuta do Python 3.12 (Debian slim).
# Pinamos a versão major para imagens reproduzíveis.
FROM python:3.12-slim

# --- 2. AMBIENTE PYTHON ----------------------------------------------
# PYTHONDONTWRITEBYTECODE=1 : evita criar arquivos __pycache__/.pyc na imagem.
# PYTHONUNBUFFERED=1        : logs saem imediatamente (sem buffer) no stdout.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# --- 3. DIRETÓRIO DE TRABALHO ---------------------------------------
WORKDIR /app

# --- 4. USUÁRIO NÃO-ROOT ---------------------------------------------
# Cria o usuário 'appuser' com home e shell. Os comandos de build seguem
# como root (necessário para instalar pacotes), mas o runtime roda como
# 'appuser' (ver USER no final), seguindo o princípio do menor privilégio.
RUN useradd --create-home --shell /bin/bash appuser

# --- 5. CACHE DE CAMADA — dependências ANTES do código ---------------
# Copiamos apenas o requirements.txt antes do restante do projeto.
# Assim, a camada "pip install" só é reconstruída quando esse arquivo
# mudar. Alterações no código do app NÃO invalidam o cache de deps.
COPY --chown=appuser:appuser requirements.txt .

# --- 6. CACHE MOUNT (BuildKit) ---------------------------------------
# O --mount=type=cache monta o diretório de cache do pip fora da imagem,
# reutilizado entre builds (mesmo quando o requirements.txt muda).
# Sem --no-cache-dir: o cache do pip fica no mount e NÃO entra na imagem,
# mantendo-a enxuta e acelerando a instalação de dependências.
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --upgrade pip \
    && pip install -r requirements.txt

# --- 7. CÓDIGO FONTE — por último ------------------------------------
# Copiamos o projeto por último (depois das dependências) para preservar
# o cache das etapas anteriores. --chown ajusta o dono para 'appuser'.
COPY --chown=appuser:appuser . .

# --- 8. EXECUÇÃO COMO NÃO-ROOT ---------------------------------------
# Todas as instruções a partir daqui (CMD/ENTRYPOINT) rodam como appuser.
USER appuser

# --- 9. PORTA DOCUMENTADA ---------------------------------------------
# Não expõe nada por si só; documenta a porta que a futura API usará
# (EXPOSE é informativo, o host binding é feito pelo docker-compose).
EXPOSE 8000

# --- 10. ENTRYPOINT DA API ----------------------------------------------
# Sobe um servidor HTTP (somente stdlib, sem framework nesta fase) que
# expõe a rota de disponibilidade /health na porta 8000.
CMD ["python", "-u", "api/main.py"]