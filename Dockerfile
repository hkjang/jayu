FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:${PATH}"

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl git \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml uv.lock README.md ./
COPY configs ./configs
COPY src ./src

RUN pip install --no-cache-dir uv \
    && uv sync --frozen --no-dev

COPY . .

RUN groupadd --gid 10001 app \
    && useradd --uid 10001 --gid app --create-home app \
    && mkdir -p state signals runs data/cache \
    && chown -R app:app state signals runs data

USER app

VOLUME ["/app/data", "/app/runs", "/app/state", "/app/signals"]

ENTRYPOINT ["jayu"]
CMD ["--help"]
