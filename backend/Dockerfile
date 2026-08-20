# ---- Base ----------------------------------------------------------------
FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# asyncpg wheels cover most platforms; build-essential is a safety net for
# source builds. Kept minimal and removed after install.
WORKDIR /app

# ---- Builder: install dependencies into a venv --------------------------
FROM base AS builder

# gdal-bin/libgdal-dev: satellite observation (FASE 16, GOES-19 + TATHU).
# The GDAL Python bindings must match the system libgdal version exactly —
# installed separately (not pinned in pyproject.toml) for that reason.
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential gdal-bin libgdal-dev git \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy only dependency metadata first for better layer caching.
COPY pyproject.toml ./
COPY app ./app
COPY engine ./engine
COPY workers ./workers
RUN pip install --upgrade pip \
    && pip install "GDAL==$(gdal-config --version)" \
    && pip install ".[satellite]" \
    && pip install --no-deps "git+https://github.com/uba/tathu.git@master"

# ---- Runtime -------------------------------------------------------------
FROM base AS runtime

# Runtime GDAL shared libs — pulled in by gdal-bin's own dependencies
# (avoids hard-coding the versioned libgdalNN package name, which varies by
# Debian release) — needed by the GDAL Python bindings from the builder.
RUN apt-get update \
    && apt-get install -y --no-install-recommends gdal-bin \
    && rm -rf /var/lib/apt/lists/*

# Non-root user.
RUN useradd --create-home --uid 1000 appuser

COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY --chown=appuser:appuser . /app

USER appuser
EXPOSE 8000

# Container-level healthcheck hits the liveness endpoint.
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0) if urllib.request.urlopen('http://127.0.0.1:8000/health').status==200 else sys.exit(1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
