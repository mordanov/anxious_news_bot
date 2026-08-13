from anxious_news_bot.preferences.services.tokens import SecureCallbackTokenFactory


def test_tokens_are_bounded_opaque_unique_and_not_stored_raw() -> None:
    factory = SecureCallbackTokenFactory()
    first_token, first_hash = factory.create()
    second_token, second_hash = factory.create()
    assert first_token != first_hash
    assert (first_token, first_hash) != (second_token, second_hash)
    assert len(first_hash) == 43
    assert "\n" not in first_hash
