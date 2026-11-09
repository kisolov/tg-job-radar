FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.5 /uv /usr/local/bin/uv
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PYTHONUNBUFFERED=1 UV_HTTP_TIMEOUT=300
COPY pyproject.toml uv.lock* README.md ./
COPY src ./src
# tgcrypto (зависимость opentele для tdata) собирается из исходников: компилятор только на время сборки;
# libglib2.0-0 остаётся — она нужна PyQt5.QtCore, через который opentele читает tdata
RUN apt-get update && apt-get install -y --no-install-recommends libglib2.0-0 gcc libc6-dev \
    && uv sync --no-dev \
    && apt-get purge -y gcc libc6-dev && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*
COPY alembic.ini ./
COPY migrations ./migrations
ENV PATH="/app/.venv/bin:$PATH"
CMD ["python", "-m", "radar.bootstrap.main"]
