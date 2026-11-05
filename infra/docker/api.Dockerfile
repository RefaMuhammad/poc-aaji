FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

# Font Unicode untuk PDF rekomendasi
RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

# Jalan sebagai pengguna non-root (U8). UID tetap supaya cocok dengan securityContext di Helm chart.
RUN useradd --uid 10001 --create-home --shell /usr/sbin/nologin app

WORKDIR /app

COPY apps/api/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY apps/api/mab_api /app/mab_api
COPY apps/api/alembic /app/alembic
COPY apps/api/alembic.ini /app/alembic.ini
COPY infra/scripts /app/infra/scripts
COPY pipeline/mab_pipeline /app/mab_pipeline
COPY rules /app/rules
COPY synthetic /app/synthetic
COPY tests /app/tests
COPY evaluation /app/evaluation

USER 10001
EXPOSE 8000
# Migrasi dijalankan terpisah (docker compose: perintah service api; Kubernetes: Job hook Helm).
# --proxy-headers: alamat klien diambil dari X-Forwarded-For yang dipasang ingress/web.
CMD ["uvicorn", "mab_api.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
