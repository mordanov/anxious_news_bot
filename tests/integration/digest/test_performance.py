from __future__ import annotations

from datetime import UTC, datetime, timedelta
from time import perf_counter

from sqlalchemy import text

NOW = datetime(2026, 1, 15, 9, 1, tzinfo=UTC)


async def test_due_claim_performance_and_burst_durability(
    digest_database,
    digest_repository,
) -> None:
    async with digest_database.session() as session:
        await session.execute(
            text(
                "INSERT INTO application_users "
                "(id, telegram_user_id, language_code) "
                "SELECT md5('digest-user-' || value::text)::uuid, "
                "700000 + value, 'en' FROM generate_series(1, 10000) value"
            )
        )
        await session.execute(
            text(
                "INSERT INTO preference_profiles (user_id, revision) "
                "SELECT id, 0 FROM application_users"
            )
        )
        await session.execute(
            text(
                "INSERT INTO digest_configurations "
                "(user_id, enabled, digest_count, schedule_local_time, "
                "timezone_name, next_due_at, schedule_revision) "
                "SELECT id, true, 10, '09:00'::time, 'UTC', "
                "CASE WHEN telegram_user_id <= 701000 THEN :due "
                "ELSE :future END, 0 FROM application_users"
            ),
            {"due": NOW - timedelta(minutes=1), "future": NOW + timedelta(days=1)},
        )

    started = perf_counter()
    first = await digest_repository.claim_due(NOW, 100)
    first_duration = perf_counter() - started
    claimed = len(first)
    deadline = NOW + timedelta(minutes=5)
    while claimed < 1000 and NOW < deadline:
        batch = await digest_repository.claim_due(NOW, 100)
        if not batch:
            break
        claimed += len(batch)

    assert len(first) == 100
    assert first_duration < 1.0
    assert claimed >= 990
