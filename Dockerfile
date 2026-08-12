FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY pyproject.toml README.md alembic.ini ./
COPY src/ src/
COPY migrations/ migrations/
COPY docker/ docker/

RUN pip install --no-cache-dir .

RUN useradd --create-home --uid 10001 bot
USER bot

CMD ["anxious-news-bot"]

