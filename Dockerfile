FROM python:3.12-slim

WORKDIR /app

RUN useradd --create-home --shell /bin/bash appuser \
    && chown -R appuser:appuser /app

USER appuser

CMD ["python", "-u", "-c", "import time; print('SynapseShop container iniciado'); time.sleep(3600)"]