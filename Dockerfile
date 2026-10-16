# The multiplayer tables (pax host) in a small image. Tables are kept in /data: mount a volume
# there, or they are lost when the container stops.
FROM python:3.13-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.12.23 /uv /bin/uv
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN uv sync --frozen --no-dev --no-editable

FROM python:3.13-slim
RUN useradd --create-home --uid 10001 pax && mkdir /data && chown pax /data
COPY --from=build --chown=pax /app/.venv /app/.venv
USER pax
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1 PORT=8080
EXPOSE 8080
CMD ["sh", "-c", "pax host --host 0.0.0.0 --port ${PORT} --saves /data"]
