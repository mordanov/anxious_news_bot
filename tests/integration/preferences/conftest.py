from __future__ import annotations

import pytest_asyncio
from sqlalchemy import text

from anxious_news_bot.infrastructure.database import Database
from anxious_news_bot.preferences.infrastructure.persistence import (
    SQLAlchemyPreferenceRepository,
)


@pytest_asyncio.fixture
async def preference_database(postgres_database_url):
    database = Database(postgres_database_url)
    try:
        yield database
    finally:
        async with database.session() as session:
            await session.execute(
                text(
                    "TRUNCATE preference_change_audit, preference_change_history, "
                    "preference_update_batches, preference_answers, "
                    "preference_question_options, preference_questions, "
                    "preference_questionnaires, preference_parameters, "
                    "preference_profiles, application_users CASCADE"
                )
            )
        await database.close()


@pytest_asyncio.fixture
async def preference_repository(preference_database):
    return SQLAlchemyPreferenceRepository(preference_database, history_context_limit=20)
