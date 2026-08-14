"""Idempotent JobQueue timing adapter for digest due/retry cycles."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from telegram.ext import JobQueue

LOGGER = logging.getLogger(__name__)


class DigestSchedulingAdapter:
    def __init__(
        self,
        job_queue: JobQueue,
        execution_service: object,
        clock: object,
        *,
        interval_seconds: int = 60,
    ) -> None:
        if interval_seconds < 1:
            raise ValueError("interval_seconds must be positive")
        self._job_queue = job_queue
        self._execution_service = execution_service
        self._clock = clock
        self._interval_seconds = interval_seconds
        self._job: Any | None = None
        self._cycle_task: asyncio.Task[None] | None = None

    def start(self) -> None:
        if self._job is not None:
            return
        self._job = self._job_queue.run_repeating(
            self.tick,
            interval=self._interval_seconds,
            first=self._interval_seconds,
            name="digest-scheduling",
            job_kwargs={
                "coalesce": True,
                "misfire_grace_time": self._interval_seconds,
            },
        )

    def stop(self) -> None:
        if self._job is not None:
            self._job.schedule_removal()
            self._job = None
        if self._cycle_task is not None and not self._cycle_task.done():
            self._cycle_task.cancel()
        self._cycle_task = None

    async def tick(self, context: object) -> None:
        del context
        if self._cycle_task is not None and not self._cycle_task.done():
            LOGGER.info("digest_cycle_already_running")
            return
        self._cycle_task = asyncio.create_task(self._run_cycle())

    async def _run_cycle(self) -> None:
        now = self._clock.now()
        try:
            due_result = await self._execution_service.run_due_cycle(now)
            if due_result.claimed_count > 0:
                LOGGER.info(
                    "digest_due_cycle_complete",
                    extra={
                        "digest": {
                            "claimed": due_result.claimed_count,
                            "completed": due_result.completed_count,
                            "failed": due_result.failed_count,
                        }
                    },
                )
        except Exception:
            LOGGER.exception("digest_due_cycle_error")

        try:
            retry_result = await self._execution_service.retry_due(now)
            if retry_result.retried_count > 0:
                LOGGER.info(
                    "digest_retry_cycle_complete",
                    extra={
                        "digest": {
                            "retried": retry_result.retried_count,
                            "completed": retry_result.completed_count,
                            "failed": retry_result.failed_count,
                        }
                    },
                )
        except Exception:
            LOGGER.exception("digest_retry_cycle_error")


class DigestRetentionScheduler:
    def __init__(
        self,
        job_queue: JobQueue,
        retention_service: object,
        *,
        interval_seconds: int = 86_400,
    ) -> None:
        if interval_seconds < 1:
            raise ValueError("interval_seconds must be positive")
        self._job_queue = job_queue
        self._retention_service = retention_service
        self._interval_seconds = interval_seconds
        self._job: Any | None = None

    def start(self) -> None:
        if self._job is not None:
            return
        self._job = self._job_queue.run_repeating(
            self.tick,
            interval=self._interval_seconds,
            first=self._interval_seconds,
            name="digest-retention",
        )

    def stop(self) -> None:
        if self._job is not None:
            self._job.schedule_removal()
            self._job = None

    async def tick(self, context: object) -> None:
        del context
        try:
            await self._retention_service.run_cleanup()
        except Exception:
            LOGGER.exception("digest_retention_cycle_error")
