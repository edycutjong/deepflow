"""
Discord & Slack webhook alerting.
Uses httpx for async HTTP POST — no extra dependencies required.
Mirrors the Telegram alert interface for drop-in use in the pipeline.
"""
from datetime import datetime, timezone

import httpx
from loguru import logger

from app.core.config import settings
from app.core.scoring import ScoreBreakdown
from app.db.models import Project


def _build_discord_embed(
    project: Project,
    breakdown: ScoreBreakdown,
    alert_type: str,
) -> dict:
    """Build a Discord embed object for rich alerts."""
    color = 0xFF4444 if alert_type == "immediate_alert" else 0xFFAA00
    emoji = "🚨" if alert_type == "immediate_alert" else "👀"
    label = "IMMEDIATE ALERT" if alert_type == "immediate_alert" else "WATCHLIST"

    fields = [
        {"name": "📊 TVL", "value": f"{breakdown.tvl_points} pts", "inline": True},
        {"name": "📈 Growth", "value": f"{breakdown.growth_points} pts", "inline": True},
        {"name": "💰 Funding", "value": f"{breakdown.funding_points} pts", "inline": True},
        {"name": "🔍 GitHub", "value": f"{breakdown.github_points} pts", "inline": True},
    ]

    if breakdown.funding_details and breakdown.funding_details != "No Tier-1/2 VCs":
        fields.append(
            {"name": "VC Details", "value": breakdown.funding_details, "inline": False}
        )

    if breakdown.github_details:
        gh_lines = []
        for hash_short, detail in breakdown.github_details.items():
            gh_lines.append(f"`{hash_short}`: {detail}")
        if gh_lines:
            fields.append(
                {"name": "GitHub Signals", "value": "\n".join(gh_lines), "inline": False}
            )

    return {
        "title": f"{emoji} {label}: {project.name}",
        "description": f"**Score: {breakdown.total_score}**",
        "color": color,
        "fields": fields,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "footer": {"text": "Silent Whale"},
    }


def _build_slack_blocks(
    project: Project,
    breakdown: ScoreBreakdown,
    alert_type: str,
) -> list[dict]:
    """Build Slack Block Kit blocks for rich alerts."""
    emoji = ":rotating_light:" if alert_type == "immediate_alert" else ":eyes:"
    label = "IMMEDIATE ALERT" if alert_type == "immediate_alert" else "WATCHLIST"

    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"{emoji} {label}: {project.name}",
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Score: {breakdown.total_score}*",
            },
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*📊 TVL:* {breakdown.tvl_points} pts"},
                {"type": "mrkdwn", "text": f"*📈 Growth:* {breakdown.growth_points} pts"},
                {"type": "mrkdwn", "text": f"*💰 Funding:* {breakdown.funding_points} pts"},
                {"type": "mrkdwn", "text": f"*🔍 GitHub:* {breakdown.github_points} pts"},
            ],
        },
    ]

    if breakdown.funding_details and breakdown.funding_details != "No Tier-1/2 VCs":
        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*VC Details:* {breakdown.funding_details}"},
            }
        )

    return blocks


async def send_discord_alert(message: str, embed: dict | None = None) -> bool:
    """Send a message to Discord via webhook. Returns True on success."""
    webhook_url = settings.DISCORD_WEBHOOK_URL
    if not webhook_url:
        return False

    payload: dict = {"content": message}
    if embed:
        payload["embeds"] = [embed]

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(webhook_url, json=payload, timeout=10.0)
            # Discord returns 204 No Content on success
            if resp.status_code in (200, 204):
                return True
            logger.warning(f"Discord webhook returned {resp.status_code}: {resp.text}")
            return False
    except Exception as e:
        logger.error(f"Failed to send Discord alert: {e}")
        return False


async def send_slack_alert(message: str, blocks: list[dict] | None = None) -> bool:
    """Send a message to Slack via incoming webhook. Returns True on success."""
    webhook_url = settings.SLACK_WEBHOOK_URL
    if not webhook_url:
        return False

    payload: dict = {"text": message}
    if blocks:
        payload["blocks"] = blocks

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(webhook_url, json=payload, timeout=10.0)
            if resp.status_code == 200:
                return True
            logger.warning(f"Slack webhook returned {resp.status_code}: {resp.text}")
            return False
    except Exception as e:
        logger.error(f"Failed to send Slack alert: {e}")
        return False


async def send_webhook_alerts(
    project: Project,
    breakdown: ScoreBreakdown,
    alert_type: str,
    message: str,
) -> dict[str, bool]:
    """
    Fan out alerts to all configured webhook destinations.
    Returns dict of {channel: success_bool}.
    """
    results: dict[str, bool] = {}

    if settings.DISCORD_WEBHOOK_URL:
        embed = _build_discord_embed(project, breakdown, alert_type)
        results["discord"] = await send_discord_alert(message, embed)

    if settings.SLACK_WEBHOOK_URL:
        blocks = _build_slack_blocks(project, breakdown, alert_type)
        results["slack"] = await send_slack_alert(message, blocks)

    if results:
        logger.info(f"Webhook results for {project.name}: {results}")

    return results
