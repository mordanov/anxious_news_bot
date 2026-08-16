from __future__ import annotations

import asyncio
import logging
import os
from decimal import Decimal

import httpx

from anxious_news_bot.config import Settings
from anxious_news_bot.logging import configure_logging
from anxious_news_bot.news.domain import AggregationStatus, SourceType
from anxious_news_bot.news.infrastructure.database import Database
from anxious_news_bot.news.infrastructure.feeds import FeedFetcher
from anxious_news_bot.news.infrastructure.persistence import SQLAlchemyNewsRepository
from anxious_news_bot.news.services.aggregate import DefaultNewsAggregator, SystemClock
from anxious_news_bot.news.services.canonicalize import CanonicalURLPolicy
from anxious_news_bot.news.services.deduplicate import DeterministicArticleDeduplicator
from anxious_news_bot.news.services.event_grouping import DeterministicEventGrouper
from anxious_news_bot.news.services.normalize import DeterministicArticleNormalizer
from anxious_news_bot.news.services.source_catalog import (
    SourceAdapterRegistry,
    SourceAdapterRouter,
)

LOGGER = logging.getLogger(__name__)

_INITIAL_DELAY_SECONDS = 30


def _build_aggregator(
    settings: Settings, client: httpx.AsyncClient
) -> DefaultNewsAggregator:
    repository = SQLAlchemyNewsRepository(Database(settings.database_url))
    feed_adapter = FeedFetcher(
        client, retry_attempts=settings.news_fetch_retry_attempts
    )
    fetcher = SourceAdapterRouter(
        SourceAdapterRegistry(
            {SourceType.RSS: feed_adapter, SourceType.ATOM: feed_adapter}
        )
    )
    normalizer = DeterministicArticleNormalizer(
        CanonicalURLPolicy(
            version=settings.news_url_policy_version,
            tracking_parameters=settings.news_tracking_parameters,
        )
    )
    return DefaultNewsAggregator(
        repository,
        fetcher,
        normalizer,
        SystemClock(),
        deduplicator=DeterministicArticleDeduplicator(
            title_threshold=Decimal(str(settings.news_near_duplicate_title_threshold)),
            content_threshold=Decimal(
                str(settings.news_near_duplicate_content_threshold)
            ),
            review_threshold=Decimal(
                str(settings.news_near_duplicate_review_threshold)
            ),
        ),
        duplicate_candidate_minimum_similarity=settings.news_near_duplicate_review_threshold,
        event_grouper=DeterministicEventGrouper(
            window_hours=settings.news_event_window_hours,
            title_weight=Decimal(str(settings.news_event_title_weight)),
            content_weight=Decimal(str(settings.news_event_content_weight)),
            topic_weight=Decimal(str(settings.news_event_topic_weight)),
            geography_weight=Decimal(str(settings.news_event_geography_weight)),
            anchor_threshold=Decimal(str(settings.news_event_anchor_threshold)),
            assignment_threshold=Decimal(str(settings.news_event_assignment_threshold)),
            review_threshold=Decimal(str(settings.news_event_review_threshold)),
        ),
        event_window_hours=settings.news_event_window_hours,
        max_concurrency=settings.news_max_concurrency,
        configuration_version=settings.news_url_policy_version,
    )


async def run(settings: Settings) -> None:
    client = httpx.AsyncClient(
        timeout=httpx.Timeout(settings.news_fetch_timeout_seconds)
    )
    aggregator = _build_aggregator(settings, client)

    LOGGER.info(
        "aggregator_starting",
        extra={
            "news": {
                "scheduler_interval_seconds": settings.news_scheduler_interval_seconds,
                "fetch_timeout_seconds": settings.news_fetch_timeout_seconds,
                "fetch_retry_attempts": settings.news_fetch_retry_attempts,
                "max_concurrency": settings.news_max_concurrency,
                "event_window_hours": settings.news_event_window_hours,
                "logical_cpu_count": os.cpu_count(),
                "cgroup_cpu_limit": _runtime_limit("/sys/fs/cgroup/cpu.max"),
                "cgroup_memory_limit": _runtime_limit("/sys/fs/cgroup/memory.max"),
            }
        },
    )

    try:
        await asyncio.sleep(_INITIAL_DELAY_SECONDS)
        while True:
            await _run_cycle(aggregator)
            await asyncio.sleep(settings.news_scheduler_interval_seconds)
    except asyncio.CancelledError:
        LOGGER.info("aggregator_stopping")
    finally:
        await client.aclose()


async def _run_cycle(aggregator: DefaultNewsAggregator) -> None:
    try:
        result = await aggregator.run_cycle()
        if result.status is AggregationStatus.ALREADY_RUNNING:
            LOGGER.info("news_cycle_already_running")
    except asyncio.CancelledError:
        raise
    except Exception:
        LOGGER.exception("news_cycle_error")


def _runtime_limit(path: str) -> str | None:
    try:
        from pathlib import Path

        return Path(path).read_text(encoding="utf-8").strip()[:100]
    except OSError:
        return None


def main() -> None:
    configure_logging()
    settings = Settings.from_env()
    asyncio.run(run(settings))
