from __future__ import annotations

import pytest_asyncio
from sqlalchemy import text

from anxious_news_bot.infrastructure.database import Database

TRUNCATE_RANKING_TABLES_SQL = text(
    "TRUNCATE ranking_audit, ranking_parameter_contributions, "
    "article_ranking_records, ranking_runs, ranking_configuration_snapshots, "
    "article_parameter_relevances, article_preference_evaluation_attempts, "
    "article_preference_evaluation_runs, deduplication_decisions, "
    "article_analyses, normalized_articles, event_groups, "
    "source_article_records, source_runs, collection_cycles, news_sources, "
    "preference_evidence, preference_change_audit, preference_change_history, "
    "preference_update_batches, explicit_preference_requests, "
    "preference_answers, preference_question_options, preference_questions, "
    "preference_questionnaires, preference_parameters, preference_profiles, "
    "application_users CASCADE"
)


@pytest_asyncio.fixture
async def ranking_database(postgres_database_url):
    database = Database(postgres_database_url)
    try:
        yield database
    finally:
        async with database.session() as session:
            await session.execute(TRUNCATE_RANKING_TABLES_SQL)
        await database.close()
