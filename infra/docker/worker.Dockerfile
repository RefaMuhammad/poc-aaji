FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

# Pustaka sistem untuk OpenCV/PaddlePaddle (dipakai PaddleOCR)
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 libgomp1 \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --uid 10001 --create-home --shell /usr/sbin/nologin app

WORKDIR /app

COPY pipeline/requirements.txt /tmp/requirements.txt
COPY pipeline/requirements-ocr.txt /tmp/requirements-ocr.txt
COPY apps/api/requirements.txt /tmp/api-requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt -r /tmp/api-requirements.txt -r /tmp/requirements-ocr.txt

# Unduh model OCR saat build, supaya worker tidak mengunduh saat memproses klaim
ARG OCR_LANG=latin
# Model disimpan di home pengguna app (~/.paddleocr), supaya terbaca saat worker jalan non-root.
USER 10001
# "import zlib" harus sebelum paddleocr (lihat mab_pipeline/ocr/engine.py).
RUN python -c "import zlib; from paddleocr import PaddleOCR; PaddleOCR(use_angle_cls=True, lang='${OCR_LANG}', show_log=False)"

USER root
# Worker memakai model database yang sama dengan API
COPY apps/api/mab_api /app/mab_api
COPY pipeline/mab_pipeline /app/mab_pipeline
COPY rules /app/rules
COPY evaluation /app/evaluation

USER 10001
CMD ["python", "-m", "mab_pipeline.worker"]
