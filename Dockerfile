# PatchVec (pave) Dockerfile
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN mkdir -p /data
RUN mkdir -p /app

WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential curl && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

COPY pave /app/pave

COPY config.yml.example /app/config-base.yml
ENV PATCHVEC_CONFIG=/app/config-base.yml

# Expose port (default 8086)
EXPOSE 8086

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD curl -fsS http://localhost:8086/health/ready || exit 1

# Run server using internal config (with workers, reload, etc.)
CMD ["python", "-m", "pave.main"]
