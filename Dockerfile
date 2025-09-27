# syntax=docker/dockerfile:1.4

# PatchVec (pave) Dockerfile

ARG BASE_IMAGE=python:3.11-slim
FROM ${BASE_IMAGE}

ARG BUILD_ID=unknown
ARG USE_CPU=0

# make build args available at runtime and in RUN shells
ENV BUILD_ID=${BUILD_ID} \
    PIP_DEFAULT_TIMEOUT=300 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATCHVEC_CONFIG=/app/config-base.yml

WORKDIR /app

# system deps for building wheels (kept minimal)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential curl ca-certificates && \
    rm -rf /var/lib/apt/lists/*

# copy packaging metadata + requirements early for good Docker caching
COPY setup.py /app/
COPY pave.toml /app/
COPY requirements.txt /app/requirements.txt
COPY requirements-cpu.txt /app/requirements-cpu.txt
COPY requirements-base.txt /app/requirements-base.txt

# Use pip cache mount so downloads/wheels persist across builds
RUN --mount=type=cache,target=/root/.cache/pip \
    if [ "${USE_CPU}" = "1" ] || [ "${USE_CPU}" = "true" ] ; then \
      echo "=== Installing CPU deps ==="; \
      pip install --progress-bar=off -r /app/requirements-cpu.txt ; \
    else \
      echo "=== Installing GPU deps ==="; \
      pip install --progress-bar=off -r /app/requirements.txt ; \
    fi

# now copy package source and install package into site-packages so `import pave` works
COPY pave /app/pave
RUN pip install --no-cache-dir --progress-bar=off /app

# Write build id file and label the image. Use ${BUILD_ID} expansion.
RUN printf "%s\n" "${BUILD_ID}" > /app/BUILD_ID
LABEL org.opencontainers.image.revision=${BUILD_ID}

EXPOSE 8086

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD curl -fsS http://localhost:8086/health/ready || exit 1

CMD ["python", "-m", "pave.main"]