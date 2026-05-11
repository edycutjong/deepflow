"""
Source Health Monitoring.
- Tracks consecutive failures per scraper source
- Auto-disables sources after N consecutive failures
- Provides health digest for Telegram reporting
"""
from datetime import datetime, timezone

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import SourceHealth


# Auto-disable after this many consecutive failures
MAX_CONSECUTIVE_FAILURES = 5


async def record_success(session: AsyncSession, source_name: str) -> None:
    """Record a successful scrape run. Resets failure counter."""
    health = await _get_or_create(session, source_name)
    health.last_success = datetime.now(timezone.utc)
    health.consecutive_failures = 0
    health.is_healthy = True
    health.last_error = None
    await session.commit()


async def record_failure(
    session: AsyncSession, source_name: str, error: str
) -> bool:
    """Record a failed scrape run. Returns True if source was auto-disabled."""
    health = await _get_or_create(session, source_name)
    health.last_failure = datetime.now(timezone.utc)
    health.consecutive_failures += 1
    health.last_error = error[:1000]  # Truncate for safety

    disabled = False
    if health.consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
        if health.is_healthy:
            logger.warning(
                f"Source '{source_name}' auto-disabled after "
                f"{health.consecutive_failures} consecutive failures"
            )
            health.is_healthy = False
            disabled = True

    await session.commit()
    return disabled


async def is_source_healthy(session: AsyncSession, source_name: str) -> bool:
    """Check if a source is healthy (enabled). Unknown sources are healthy."""
    result = await session.execute(
        select(SourceHealth).where(SourceHealth.source_name == source_name)
    )
    health = result.scalar_one_or_none()
    if health is None:
        return True  # New/unknown sources are healthy by default
    return health.is_healthy


async def re_enable_source(session: AsyncSession, source_name: str) -> bool:
    """Manually re-enable a disabled source. Returns True if found."""
    result = await session.execute(
        select(SourceHealth).where(SourceHealth.source_name == source_name)
    )
    health = result.scalar_one_or_none()
    if health is None:
        return False

    health.is_healthy = True
    health.consecutive_failures = 0
    health.last_error = None
    await session.commit()
    logger.info(f"Source '{source_name}' manually re-enabled")
    return True


async def get_health_digest(session: AsyncSession) -> str:
    """Generate a health digest summary for all tracked sources."""
    result = await session.execute(
        select(SourceHealth).order_by(SourceHealth.source_name)
    )
    sources = result.scalars().all()

    if not sources:
        return "📊 *Source Health*: No sources tracked yet."

    lines = ["📊 *Source Health Digest*", ""]

    for s in sources:
        status = "✅" if s.is_healthy else "❌"
        failures = f" ({s.consecutive_failures} failures)" if s.consecutive_failures > 0 else ""
        last_ok = (
            s.last_success.strftime("%Y-%m-%d %H:%M UTC")
            if s.last_success
            else "never"
        )
        lines.append(f"{status} *{s.source_name}*{failures}")
        lines.append(f"   Last success: {last_ok}")

        if not s.is_healthy and s.last_error:
            lines.append(f"   Error: `{s.last_error[:100]}`")

        lines.append("")

    healthy = sum(1 for s in sources if s.is_healthy)
    total = len(sources)
    lines.append(f"_{healthy}/{total} sources healthy_")

    return "\n".join(lines)


async def _get_or_create(
    session: AsyncSession, source_name: str
) -> SourceHealth:
    """Get existing SourceHealth or create a new one."""
    result = await session.execute(
        select(SourceHealth).where(SourceHealth.source_name == source_name)
    )
    health = result.scalar_one_or_none()

    if health is None:
        health = SourceHealth(
            source_name=source_name,
            is_healthy=True,
            consecutive_failures=0,
        )
        session.add(health)
        await session.flush()

    return health
