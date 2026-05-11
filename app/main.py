"""
Silent Whale — main entry point.
APScheduler AsyncIOScheduler with full pipeline:
  DefiLlama → GitHub → Funding → Score → Alert
Boot-time run, SIGTERM handling, health check server, source health tracking.
"""
import asyncio
import signal

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from loguru import logger

from app.core.logging import setup_logging
from app.core.healthcheck import set_healthy, start_health_server
from app.core.source_health import (
    is_source_healthy,
    record_failure,
    record_success,
    get_health_digest,
)
from app.alerts.telegram import flush_queued_alerts, send_telegram_alert
from app.db.session import async_session
from app.pipeline.score_pipeline import run_scoring_pipeline
from app.scrapers.defillama import scrape_protocols
from app.scrapers.funding import scrape_funding_rounds
from app.scrapers.github import scrape_github_signals

scheduler = AsyncIOScheduler()


async def _run_source(source_name: str, coro) -> bool:
    """Run a scraper with source health tracking. Returns True on success."""
    async with async_session() as session:
        if not await is_source_healthy(session, source_name):
            logger.warning(f"Skipping disabled source: {source_name}")
            return False

    try:
        async with async_session() as session:
            await coro(session)
        async with async_session() as session:
            await record_success(session, source_name)
        return True
    except Exception as e:
        logger.error(f"Source '{source_name}' failed: {e}")
        async with async_session() as session:
            disabled = await record_failure(session, source_name, str(e))
            if disabled:
                await send_telegram_alert(
                    f"⚠️ Source `{source_name}` auto-disabled after "
                    f"consecutive failures.\nLast error: `{str(e)[:200]}`"
                )
        return False


async def run_full_cycle() -> None:
    """Scrape → Score → Alert in sequence with source health tracking."""
    logger.info("Starting full cycle...")

    # Phase 1: Scrape all sources
    await _run_source("defillama", scrape_protocols)
    await _run_source("github_signals", scrape_github_signals)
    await _run_source("funding_rounds", scrape_funding_rounds)

    # Phase 2: Score & alert
    try:
        async with async_session() as session:
            scored = await run_scoring_pipeline(session)
        logger.info(f"Scoring pipeline complete: {scored} projects scored.")
    except Exception as e:
        logger.error(f"Scoring pipeline failed: {e}")

    logger.info("Full cycle complete.")


async def run_alert_flush_job() -> None:
    """Flush alerts queued during quiet hours."""
    async with async_session() as session:
        sent = await flush_queued_alerts(session)
    if sent > 0:
        logger.info(f"Flushed {sent} queued alerts.")


async def run_health_digest_job() -> None:
    """Send daily source health digest via Telegram."""
    async with async_session() as session:
        digest = await get_health_digest(session)
    await send_telegram_alert(digest)


async def safe_boot_run() -> None:
    """Boot-time initial run — non-fatal on failure."""
    try:
        await run_full_cycle()
    except Exception as e:
        logger.error(f"Boot-time cycle failed (non-fatal): {e}")


def handle_sigterm(*_: object) -> None:
    logger.info("SIGTERM received, shutting down scheduler...")
    scheduler.shutdown(wait=False)


async def main() -> None:
    # Configure logging first
    setup_logging()

    signal.signal(signal.SIGTERM, handle_sigterm)
    signal.signal(signal.SIGINT, handle_sigterm)

    logger.info("Silent Whale starting up...")

    # Start health check server
    health_runner = await start_health_server()

    # Boot-time initial run
    await safe_boot_run()

    # Mark as healthy after boot
    set_healthy(True)

    # Schedule recurring jobs
    scheduler.add_job(
        run_full_cycle,
        "cron",
        hour="*/12",
        id="full_cycle",
        replace_existing=True,
    )

    # Flush queued alerts every hour (for quiet hours drain)
    scheduler.add_job(
        run_alert_flush_job,
        "cron",
        minute=0,
        id="alert_flush",
        replace_existing=True,
    )

    # Daily health digest at 09:00 local
    scheduler.add_job(
        run_health_digest_job,
        "cron",
        hour=9,
        minute=0,
        id="health_digest",
        replace_existing=True,
    )

    scheduler.start()
    logger.info(
        "Scheduler started. Full cycle every 12h, "
        "alert flush every 1h, health digest at 09:00."
    )

    # Keep the event loop alive
    try:
        while True:
            await asyncio.sleep(3600)
    except (KeyboardInterrupt, SystemExit):
        logger.info("Shutting down...")
        set_healthy(False)
        scheduler.shutdown(wait=False)
        await health_runner.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
