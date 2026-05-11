"""
Telegram alerting with quiet hours enforcement, deduplication,
and score threshold routing (immediate_alert vs watchlist).
Uses python-telegram-bot v20+ async API.
"""
from datetime import datetime, timezone

import pytz
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from telegram import Bot

from app.core.config import settings
from app.core.config_loader import get_config
from app.core.scoring import ScoreBreakdown
from app.db.models import AlertQueue, Project


def _is_quiet_hours(now_utc: datetime) -> bool:
    """Check if current time falls within configured quiet hours."""
    cfg = get_config().operational
    tz = pytz.timezone(cfg.timezone)
    local_now = now_utc.astimezone(tz)

    start_parts = cfg.quiet_hours[0].split(":")
    end_parts = cfg.quiet_hours[1].split(":")
    start_h, start_m = int(start_parts[0]), int(start_parts[1])
    end_h, end_m = int(end_parts[0]), int(end_parts[1])

    current_minutes = local_now.hour * 60 + local_now.minute
    start_minutes = start_h * 60 + start_m
    end_minutes = end_h * 60 + end_m

    # Handle overnight quiet hours (e.g., 23:00 -> 07:00)
    if start_minutes > end_minutes:
        return current_minutes >= start_minutes or current_minutes < end_minutes
    else:
        return start_minutes <= current_minutes < end_minutes


async def _is_duplicate_alert(
    session: AsyncSession,
    project_id: int,
    current_score: float,
) -> bool:
    """Check if a recent alert exists within the dedup delta range."""
    cfg = get_config().thresholds
    result = await session.execute(
        select(AlertQueue)
        .where(AlertQueue.project_id == project_id)
        .where(AlertQueue.sent.is_(True))
        .order_by(AlertQueue.created_at.desc())
        .limit(1)
    )
    last_alert = result.scalar_one_or_none()

    if last_alert is None:
        return False

    return abs(current_score - last_alert.score_at_alert) < cfg.alert_dedup_delta


def _format_alert_message(
    project: Project,
    breakdown: ScoreBreakdown,
    alert_type: str,
) -> str:
    """Format a rich Telegram alert message."""
    emoji = "🚨" if alert_type == "immediate_alert" else "👀"
    label = "IMMEDIATE ALERT" if alert_type == "immediate_alert" else "WATCHLIST"

    lines = [
        f"{emoji} *{label}*: {project.name}",
        f"Score: *{breakdown.total_score}*",
        "",
        f"📊 TVL: {breakdown.tvl_points} pts",
        f"📈 Growth: {breakdown.growth_points} pts",
        f"💰 Funding: {breakdown.funding_points} pts",
        f"🔍 GitHub: {breakdown.github_points} pts",
        "",
        f"💰 {breakdown.funding_details}",
    ]

    if breakdown.github_details:
        lines.append("")
        for hash_short, detail in breakdown.github_details.items():
            lines.append(f"  `{hash_short}`: {detail}")

    return "\n".join(lines)


async def send_telegram_alert(message: str) -> bool:
    """Send a message via Telegram bot. Returns True on success."""
    if not settings.TELEGRAM_BOT_TOKEN or not settings.TELEGRAM_CHAT_ID:
        logger.warning("Telegram credentials not configured, skipping alert")
        return False

    try:
        bot = Bot(token=settings.TELEGRAM_BOT_TOKEN)
        await bot.send_message(
            chat_id=settings.TELEGRAM_CHAT_ID,
            text=message,
            parse_mode="Markdown",
        )
        return True
    except Exception as e:
        logger.error(f"Failed to send Telegram alert: {e}")
        return False


async def evaluate_and_alert(
    session: AsyncSession,
    project: Project,
    breakdown: ScoreBreakdown,
    now: datetime | None = None,
) -> None:
    """
    Evaluate score against thresholds, enqueue alert, and send if not quiet hours.
    Handles deduplication via alert_dedup_delta.
    """
    if now is None:
        now = datetime.now(timezone.utc)

    cfg = get_config().thresholds
    score = breakdown.total_score

    # Determine alert type
    alert_type: str | None = None
    if score >= cfg.immediate_alert:
        alert_type = "immediate_alert"
    elif score >= cfg.watchlist:
        alert_type = "watchlist"

    if alert_type is None:
        return

    # Deduplication check
    if await _is_duplicate_alert(session, project.id, score):
        logger.debug(
            f"Skipping duplicate alert for {project.name} "
            f"(score={score}, delta < {cfg.alert_dedup_delta})"
        )
        return

    message = _format_alert_message(project, breakdown, alert_type)

    # Enqueue the alert
    alert = AlertQueue(
        project_id=project.id,
        alert_type=alert_type,
        score_at_alert=score,
        message=message,
        sent=False,
    )
    session.add(alert)
    await session.flush()

    # Send if not quiet hours
    if _is_quiet_hours(now):
        logger.info(
            f"Alert queued for {project.name} (score={score}) — "
            f"quiet hours, will send later"
        )
    else:
        sent = await send_telegram_alert(message)
        if sent:
            alert.sent = True
            alert.sent_at = now
            logger.info(f"Alert sent for {project.name} (score={score})")

    await session.commit()


async def flush_queued_alerts(session: AsyncSession) -> int:
    """Send all unsent alerts that were queued during quiet hours. Returns count sent."""
    now = datetime.now(timezone.utc)

    if _is_quiet_hours(now):
        return 0

    result = await session.execute(
        select(AlertQueue)
        .where(AlertQueue.sent.is_(False))
        .order_by(AlertQueue.created_at.asc())
    )
    unsent = result.scalars().all()

    sent_count = 0
    for alert in unsent:
        if alert.message and await send_telegram_alert(alert.message):
            alert.sent = True
            alert.sent_at = now
            sent_count += 1

    if sent_count > 0:
        await session.commit()
        logger.info(f"Flushed {sent_count} queued alerts")

    return sent_count
