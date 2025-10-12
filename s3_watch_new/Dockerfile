# Dockerfile
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# system deps (optional but handy for ssl/ca)
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# drop privileges
RUN useradd -m appuser
USER appuser

COPY s3_watch.py .

# default envs (override in k8s)
ENV DATABASE_URL=sqlite+aiosqlite:////data/s3_watch.db \
    SCAN_INTERVAL_SECONDS=600 \
    REFRESH_INTERVAL_SECONDS=3600

EXPOSE 8000
CMD ["uvicorn", "s3_watch:app", "--host", "0.0.0.0", "--port", "8000"]
