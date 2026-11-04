FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

WORKDIR /app

# PaddleOCR dan dependensi sistemnya ditambahkan di M4.
COPY pipeline/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY pipeline/mab_pipeline /app/mab_pipeline
COPY rules /app/rules

CMD ["python", "-m", "mab_pipeline.worker"]
