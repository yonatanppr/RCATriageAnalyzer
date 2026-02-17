FROM python:3.12-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends build-essential libpq-dev && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app/backend

COPY backend /app/backend

RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir /app/backend

COPY fixtures /app/fixtures

CMD ["celery", "-A", "app.tasks:celery_app", "worker", "--loglevel=info"]
