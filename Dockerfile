FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY pyproject.toml README.md alembic.ini ./
COPY src/ src/
COPY migrations/ migrations/
COPY docker/ docker/
COPY sources.json sources.json

RUN pip install --no-cache-dir .
RUN anxious-news-sources validate /app/sources.json

RUN useradd --create-home --uid 10001 bot
USER bot

CMD ["anxious-news-bot"]
