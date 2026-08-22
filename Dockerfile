# API de conversión doc2md (Fase 2/3).
# Imagen mínima para Railway/Render: instala el motor + FastAPI y arranca uvicorn.
FROM python:3.11-slim

# No escribir .pyc y salida sin buffer (logs JSON visibles al instante en la plataforma).
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Instalar primero los metadatos + el paquete (aprovecha la caché de capas).
COPY pyproject.toml README.md ./
COPY doc2md ./doc2md
RUN pip install --no-cache-dir ".[api]"

# Railway/Render inyectan el puerto en $PORT; por defecto 8000 en local.
ENV PORT=8000
EXPOSE 8000

CMD ["sh", "-c", "uvicorn doc2md.adapters.inbound.http:app --host 0.0.0.0 --port ${PORT:-8000}"]
