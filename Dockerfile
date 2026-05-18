FROM python:3.11-slim

RUN apt-get update && \
    apt-get install -y supervisor && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Python deps (cached layer)
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

# App code
COPY backend/ backend/
COPY frontend/ frontend/

COPY supervisord.conf /etc/supervisor/conf.d/pedroos.conf

# Defaults — overridden by fly secrets/env
ENV DATABASE_URL="sqlite+aiosqlite:////data/pedro.db"
ENV UPLOADS_DIR="/data/uploads"
ENV WA_GATEWAY_URL="http://localhost:3000"
ENV MALLOC_ARENA_MAX=2
ENV PYTHONDONTWRITEBYTECODE=1

RUN mkdir -p /data/uploads

EXPOSE 8080

CMD ["/usr/bin/supervisord", "-n", "-c", "/etc/supervisor/conf.d/pedroos.conf"]
