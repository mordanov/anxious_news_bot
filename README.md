# Anxious News Bot

Minimal Telegram bot template for the future personalized news application.
Currently it exposes only `/start` and replies with a readiness message.

## Run locally

1. Create a bot with [BotFather](https://t.me/BotFather).
2. Copy `.env.example` to `.env` and replace the placeholder token.
3. Install and run:

   ```bash
   python -m venv .venv
   . .venv/bin/activate
   pip install -e '.[dev]'
   export TELEGRAM_BOT_TOKEN="$(sed -n 's/^TELEGRAM_BOT_TOKEN=//p' .env)"
   anxious-news-bot
   ```

The Telegram layer is intentionally limited to adapter code so future application
logic can be added independently.

