# miAssist's image, hitsai/miassist-server (PADR ADR-014; Foundation task 4.1).
#
# - python:3.13-slim, pinned by tag (never `latest`); two stages, so no compiler or build tool
#   reaches the final image.
# - Runs as the non-root user 10001 and works with a READ-ONLY root filesystem: it writes only to a
#   mounted /tmp (the pod mounts an emptyDir there).
# - `python -m miassist` serves (uvicorn, no access log); with MIASSIST_MIGRATE=1 it migrates and
#   exits (the init container).

FROM python:3.13-slim AS build
WORKDIR /build
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-compile . \
    && /opt/venv/bin/python -m compileall -q /opt/venv/lib

FROM python:3.13-slim
ARG APP_VERSION=0.0.0
LABEL org.opencontainers.image.title="miassist-server" \
      org.opencontainers.image.version="${APP_VERSION}" \
      org.opencontainers.image.licenses="MIT"
ENV PATH=/opt/venv/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MIASSIST_ALEMBIC_DIR=/app/alembic
RUN groupadd --system --gid 10001 miassist \
    && useradd --system --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin miassist
COPY --from=build /opt/venv /opt/venv
WORKDIR /app
COPY alembic.ini ./
COPY alembic ./alembic
USER 10001:10001
EXPOSE 8765
CMD ["python", "-m", "miassist"]
