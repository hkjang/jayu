FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    HOME="/home/app" \
    PATH="/app/.venv/bin:${PATH}"

WORKDIR /app

RUN groupadd --gid 10001 app \
    && useradd --uid 10001 --gid app --create-home app

COPY --chown=app:app pyproject.toml uv.lock README.md ./
COPY --chown=app:app configs/config.sample.json configs/portfolio_mapping.json ./configs/
COPY --chown=app:app configs/strategy_spaces ./configs/strategy_spaces
COPY --chown=app:app src ./src

RUN pip install --no-cache-dir uv==0.11.21 \
    && uv sync --frozen --no-dev

RUN mkdir -p state signals runs data/cache \
    && chown -R app:app state signals runs data

USER app

VOLUME ["/app/data", "/app/runs", "/app/state", "/app/signals"]

ENTRYPOINT ["jayu"]
CMD ["--help"]
