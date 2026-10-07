FROM python:3.12.14-slim-bookworm@sha256:392307d22300de8b5986851a12d9176dfc0fc073e65bf6523ebd7dcbeb23564e AS wheel-builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /build
COPY requirements-dev.lock ./requirements-dev.lock
RUN python -m pip install --no-cache-dir -r requirements-dev.lock
RUN python -m pip install --no-cache-dir setuptools==84.0.0

COPY pyproject.toml README.md ./
COPY apps/api ./apps/api
COPY apps/web ./apps/web
COPY packages/core ./packages/core
RUN python -m build --wheel --no-isolation --outdir /wheel

FROM python:3.12.14-slim-bookworm@sha256:392307d22300de8b5986851a12d9176dfc0fc073e65bf6523ebd7dcbeb23564e AS runtime

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TMPDIR=/tmp

WORKDIR /app
COPY requirements-runtime.lock ./requirements-runtime.lock
RUN python -m pip install --no-cache-dir -r requirements-runtime.lock \
    && useradd --system --uid 10001 --home-dir /nonexistent --shell /usr/sbin/nologin rapport

RUN mkdir -p /tmp/wheels
COPY --from=wheel-builder /wheel/*.whl /tmp/wheels/
RUN python -m pip install --no-cache-dir --no-deps /tmp/wheels/*.whl \
    && rm -rf /tmp/wheels \
    && chown 10001:10001 /app

USER 10001:10001
EXPOSE 5000
ENTRYPOINT ["rapport-auditor"]
