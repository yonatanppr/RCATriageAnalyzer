FROM python:3.12-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends build-essential libpq-dev && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app/backend

COPY backend /app/backend

RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir "/app/backend[dev]"

COPY fixtures /app/fixtures

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
