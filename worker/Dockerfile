FROM python:3.12-slim

WORKDIR /app/backend

COPY backend /app/backend
RUN pip install --no-cache-dir --upgrade pip && pip install --no-cache-dir /app/backend

COPY fixtures /app/fixtures

CMD ["celery", "-A", "app.tasks:celery_app", "worker", "--loglevel=info"]
