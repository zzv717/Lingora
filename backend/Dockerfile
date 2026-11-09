# Python 3.11 slim base with optional Tesseract OCR and PostgreSQL support
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DEBIAN_FRONTEND=noninteractive

WORKDIR /app

# Install system dependencies:
# - build-essential & libpq-dev for PostgreSQL adapter
# - tesseract-ocr & languages (eng, uzb, uzb_cyrl) for scanned textbook processing
# - ffmpeg / curl for diagnostics
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    curl \
    tesseract-ocr \
    tesseract-ocr-eng \
    tesseract-ocr-uzb \
    tesseract-ocr-uzb-cyrl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY . .

# Create storage and data mountpoints
RUN mkdir -p /data/storage ./data

EXPOSE 8000

CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
