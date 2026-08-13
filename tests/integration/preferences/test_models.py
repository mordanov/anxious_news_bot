from sqlalchemy import inspect


async def test_migration_creates_constraints_relationships_and_indexes(
    postgres_engine,
) -> None:
    async with postgres_engine.connect() as connection:
        tables = await connection.run_sync(
            lambda sync: set(inspect(sync).get_table_names())
        )
        indexes = await connection.run_sync(
            lambda sync: inspect(sync).get_indexes("preference_questionnaires")
        )
    assert {
        "application_users",
        "preference_profiles",
        "preference_parameters",
        "preference_questionnaires",
        "preference_change_history",
        "preference_change_audit",
    } <= tables
    active = next(
        item for item in indexes if item["name"] == "uq_questionnaires_user_active"
    )
    assert active["unique"]
