FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

WORKDIR /app

COPY apps/api/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY apps/api/mab_api /app/mab_api
COPY pipeline/mab_pipeline /app/mab_pipeline
COPY rules /app/rules
COPY synthetic /app/synthetic
COPY tests /app/tests

EXPOSE 8000
CMD ["uvicorn", "mab_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
