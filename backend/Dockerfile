FROM python:3.12-slim

WORKDIR /app/backend

COPY backend /app/backend
RUN pip install --no-cache-dir --upgrade pip && pip install --no-cache-dir /app/backend[dev]

COPY fixtures /app/fixtures

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
