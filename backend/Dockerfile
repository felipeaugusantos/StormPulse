# ---- Base ------------------------------------------------------------------
# Pinned by digest (not just tag) for reproducibility — "python:3.12-slim"
# is a moving pointer, this SHA is not. Re-pin deliberately (Dependabot
# tracks base images too) rather than letting it drift silently.
FROM python:3.12-slim@sha256:2c941e860699f878900b0edc2403613c234d4b32eda3cc9fa7036991a2a63c4a AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# ---- Builder (base): install dependencies into a venv, no GDAL/TATHU ------
# Everything the API and non-satellite workers need. Kept free of GDAL/TATHU
# so the default image (SATELLITE_ENABLED=false, the project default) stays
# smaller and has a materially smaller attack/dependency surface.
FROM base AS builder-base

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy only dependency metadata first for better layer caching.
COPY pyproject.toml ./
COPY app ./app
COPY engine ./engine
COPY workers ./workers
RUN pip install --upgrade pip \
    && pip install .

# ---- Builder (satellite): adds GDAL + TATHU on top of the base venv -------
FROM builder-base AS builder-satellite

# gdal-bin/libgdal-dev: satellite observation (FASE 16, GOES-19 + TATHU).
# The GDAL Python bindings must match the system libgdal version exactly —
# installed separately (not pinned in pyproject.toml) for that reason.
RUN apt-get update \
    && apt-get install -y --no-install-recommends gdal-bin libgdal-dev git \
    && rm -rf /var/lib/apt/lists/*

# TATHU pinned to an audited commit SHA, not a floating branch — "@master"
# can change contents under us at any time without any signal in this repo's
# own history. Re-pin deliberately after reviewing the diff, same as any
# other dependency bump. Audited 2026-08-22: official INPE repo (uba/tathu),
# MIT license, no dynamic code execution in the package (checked for
# eval/exec/dynamic-import/shell-string-execution patterns), only a
# subprocess call with an argument list in `tathu/downloader/mergir.py` — a
# downloader module this project never imports (only the detection/tracking
# pieces pulled in via the `satellite` extra are used, see
# workers/satellite_pipeline.py).
ARG TATHU_COMMIT_SHA=64f970eccad8f702498afd97c97b1a70afeecc10
RUN pip install "GDAL==$(gdal-config --version)" \
    && pip install ".[satellite]" \
    && pip install --no-deps "git+https://github.com/uba/tathu.git@${TATHU_COMMIT_SHA}"

# ---- Runtime (base): API + non-satellite workers ---------------------------
FROM base AS runtime-base

# Non-root user.
RUN useradd --create-home --uid 1000 appuser

COPY --from=builder-base /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY --chown=appuser:appuser . /app

USER appuser
EXPOSE 8000

# Container-level healthcheck hits the liveness endpoint.
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0) if urllib.request.urlopen('http://127.0.0.1:8000/health').status==200 else sys.exit(1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

# ---- Runtime (satellite): everything above, plus GDAL + TATHU -------------
# Selected explicitly (docker compose build --target / docker build --target)
# when SATELLITE_ENABLED=true. Never the default — see docker-compose.yml.
FROM runtime-base AS runtime-satellite

USER root

# Runtime GDAL shared libs — pulled in by gdal-bin's own dependencies
# (avoids hard-coding the versioned libgdalNN package name, which varies by
# Debian release) — needed by the GDAL Python bindings from the builder.
RUN apt-get update \
    && apt-get install -y --no-install-recommends gdal-bin \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder-satellite /opt/venv /opt/venv

USER appuser
