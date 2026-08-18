from anxious_news_bot.app import build_application
from anxious_news_bot.config import Settings


def test_build_application_registers_count_and_digest_services() -> None:
    application = build_application(Settings(telegram_bot_token="123456:ABCDEF"))

    commands = {
        command
        for handler in application.handlers[0]
        for command in (getattr(handler, "commands", ()) or ())
    }
    assert {
        "start",
        "language",
        "timezone",
        "news",
        "tune",
        "specify",
        "count",
    } <= commands
    assert "digest_repository" in application.bot_data
    assert "digest_configuration_service" in application.bot_data
