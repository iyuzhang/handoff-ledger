ARG PYTHON_IMAGE=docker.io/library/python:3.12-slim-bookworm
ARG UV_IMAGE=ghcr.io/astral-sh/uv:0.8.0

FROM ${UV_IMAGE} AS uv
FROM ${PYTHON_IMAGE} AS build
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_PYTHON_DOWNLOADS=never UV_LINK_MODE=copy
WORKDIR /opt/handoff
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project
COPY README.md LICENSE ./
COPY handoff_ledger ./handoff_ledger
RUN uv sync --locked --no-dev --no-editable

FROM ${PYTHON_IMAGE}
RUN groupadd --gid 10001 handoff \
    && useradd --uid 10001 --gid handoff --home-dir /data --no-create-home --shell /usr/sbin/nologin handoff \
    && install -d -o handoff -g handoff /data
COPY --from=build /opt/handoff/.venv /opt/handoff/.venv
ENV PATH="/opt/handoff/.venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HANDOFF_DATA_DIR=/data
WORKDIR /opt/handoff
USER 10001:10001
EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=4s --start-period=5s --retries=3 \
    CMD ["python", "-c", "from urllib.request import urlopen; urlopen('http://127.0.0.1:8080/api/health', timeout=3).close()"]
ENTRYPOINT ["handoff-ledger"]
CMD ["serve", "--host", "0.0.0.0", "--port", "8080"]
