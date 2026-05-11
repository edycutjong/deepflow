"""
Independent metrics collector. Session injected via constructor.
Checks exc_type to rollback poisoned scraper transactions before saving metric.
"""
import time

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.metrics import IngestionMetric


class MetricsCollector:
    """
    Async context manager for tracking ingestion metrics.
    Takes a required session to enforce dependency injection
    and ensure testability without module-level DB imports.
    """

    def __init__(self, source_name: str, session: AsyncSession):
        self.source_name = source_name
        self.session = session
        self.start_time = 0.0
        self.projects_upserted = 0
        self.records_inserted = 0
        self.api_calls_made = 0
        self.api_errors = 0
        self.error_details: str | None = None

    async def __aenter__(self) -> "MetricsCollector":
        self.start_time = time.perf_counter()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):  # type: ignore[no-untyped-def]
        duration = round(time.perf_counter() - self.start_time, 2)

        if exc_type is not None:
            self.api_errors += 1
            self.error_details = str(exc_val)
            logger.error(f"[{self.source_name}] Scraper failed mid-flight: {exc_val}")
            # The scraper exploded. We MUST rollback its dirty transaction state
            # before we try to use this same session to save our metrics.
            await self.session.rollback()

        metric = IngestionMetric(
            source_name=self.source_name,
            duration_seconds=duration,
            projects_upserted=self.projects_upserted,
            records_inserted=self.records_inserted,
            api_calls_made=self.api_calls_made,
            api_errors=self.api_errors,
            error_details=self.error_details,
        )

        self.session.add(metric)
        try:
            await self.session.commit()
            logger.info(
                f"[{self.source_name}] Metrics saved | Duration: {duration}s | "
                f"Upserted: {self.projects_upserted} | Errors: {self.api_errors}"
            )
        except Exception as e:
            await self.session.rollback()
            logger.error(f"Failed to commit metrics for {self.source_name}: {e}")
