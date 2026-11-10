# syntax=docker/dockerfile:1

# --- TAHAP 1: BUILDER ---
FROM python:3.12-slim AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libffi-dev \
    libssl-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt


# --- TAHAP 2: RUNNER ---
FROM python:3.12-slim AS runner

WORKDIR /app

# Install system dependencies (curl & ookla speedtest CLI)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    tzdata \
    && curl -s https://packagecloud.io/install/repositories/ookla/speedtest-cli/script.deb.sh | bash \
    && apt-get install -y --no-install-recommends speedtest \
    && rm -rf /var/lib/apt/lists/*

# Salin library Python dari builder
COPY --from=builder /install /usr/local

# Buat user non-root demi keamanan
RUN groupadd -r botgroup && useradd -r -g botgroup -d /app botuser \
    && mkdir -p /app/logs /app/data \
    && chown -R botuser:botgroup /app

# Salin seluruh kode aplikasi
COPY --chown=botuser:botgroup . /app

USER botuser

# Environment variables default
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TZ=Asia/Jakarta

# Port untuk HTTP API receiver logbook
EXPOSE 8088

# Jalankan entrypoint bot dengan sinyal unbuffered
CMD ["python", "main.py"]

