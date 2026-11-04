FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

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

EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && uvicorn mab_api.main:app --host 0.0.0.0 --port 8000"]
