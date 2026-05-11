"""
Tests for Discord & Slack webhook alerting.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.alerts.webhooks import (
    _build_discord_embed,
    _build_slack_blocks,
    send_discord_alert,
    send_slack_alert,
    send_webhook_alerts,
)
from app.core.scoring import ScoreBreakdown
from app.db.models import Project


@pytest.fixture
def mock_project():
    p = MagicMock(spec=Project)
    p.id = 1
    p.name = "TestProtocol"
    p.slug = "test-protocol"
    return p


@pytest.fixture
def high_score_breakdown():
    return ScoreBreakdown(
        tvl_points=18.0,
        growth_points=12.0,
        funding_points=20.0,
        github_points=25.0,
        total_score=75.0,
        funding_details="Leads: a16z | Raw: 20 | Decay: 1.0x | Date: 2026-01-15",
        github_details={"abc1234": "Keyword 'tge' (2026-01-10). Raw: 25. Decay: 0.95x."},
    )


class TestDiscordEmbed:
    def test_immediate_alert_embed(self, mock_project, high_score_breakdown):
        embed = _build_discord_embed(mock_project, high_score_breakdown, "immediate_alert")
        assert embed["title"].startswith("🚨")
        assert "TestProtocol" in embed["title"]
        assert embed["color"] == 0xFF4444
        assert "75.0" in embed["description"]
        assert len(embed["fields"]) >= 4  # TVL, Growth, Funding, GitHub + details

    def test_watchlist_embed(self, mock_project, high_score_breakdown):
        embed = _build_discord_embed(mock_project, high_score_breakdown, "watchlist")
        assert embed["title"].startswith("👀")
        assert embed["color"] == 0xFFAA00

    def test_no_vc_details_omitted(self, mock_project):
        breakdown = ScoreBreakdown(total_score=55.0, funding_details="No Tier-1/2 VCs")
        embed = _build_discord_embed(mock_project, breakdown, "watchlist")
        field_names = [f["name"] for f in embed["fields"]]
        assert "VC Details" not in field_names


class TestSlackBlocks:
    def test_immediate_alert_blocks(self, mock_project, high_score_breakdown):
        blocks = _build_slack_blocks(mock_project, high_score_breakdown, "immediate_alert")
        assert blocks[0]["type"] == "header"
        assert ":rotating_light:" in blocks[0]["text"]["text"]
        assert len(blocks) >= 3  # Header, score, fields

    def test_watchlist_blocks(self, mock_project, high_score_breakdown):
        blocks = _build_slack_blocks(mock_project, high_score_breakdown, "watchlist")
        assert ":eyes:" in blocks[0]["text"]["text"]


class TestSendDiscordAlert:
    @pytest.mark.asyncio
    async def test_skips_when_no_url(self, mock_config):
        with patch("app.alerts.webhooks.settings") as mock_settings:
            mock_settings.DISCORD_WEBHOOK_URL = ""
            result = await send_discord_alert("test message")
            assert result is False

    @pytest.mark.asyncio
    async def test_success_on_204(self, mock_config):
        mock_response = MagicMock()
        mock_response.status_code = 204
        mock_response.text = ""

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("app.alerts.webhooks.settings") as mock_settings, \
             patch("app.alerts.webhooks.httpx.AsyncClient", return_value=mock_client):
            mock_settings.DISCORD_WEBHOOK_URL = "https://discord.com/api/webhooks/test"
            result = await send_discord_alert("test message")
            assert result is True

    @pytest.mark.asyncio
    async def test_failure_on_error(self, mock_config):
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.text = "Bad Request"

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("app.alerts.webhooks.settings") as mock_settings, \
             patch("app.alerts.webhooks.httpx.AsyncClient", return_value=mock_client):
            mock_settings.DISCORD_WEBHOOK_URL = "https://discord.com/api/webhooks/test"
            result = await send_discord_alert("test message")
            assert result is False


class TestSendSlackAlert:
    @pytest.mark.asyncio
    async def test_skips_when_no_url(self, mock_config):
        with patch("app.alerts.webhooks.settings") as mock_settings:
            mock_settings.SLACK_WEBHOOK_URL = ""
            result = await send_slack_alert("test message")
            assert result is False

    @pytest.mark.asyncio
    async def test_success_on_200(self, mock_config):
        mock_response = MagicMock()
        mock_response.status_code = 200

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("app.alerts.webhooks.settings") as mock_settings, \
             patch("app.alerts.webhooks.httpx.AsyncClient", return_value=mock_client):
            mock_settings.SLACK_WEBHOOK_URL = "https://hooks.slack.com/services/test"
            result = await send_slack_alert("test message")
            assert result is True


class TestSendWebhookAlerts:
    @pytest.mark.asyncio
    async def test_no_webhooks_configured(self, mock_project, high_score_breakdown, mock_config):
        with patch("app.alerts.webhooks.settings") as mock_settings:
            mock_settings.DISCORD_WEBHOOK_URL = ""
            mock_settings.SLACK_WEBHOOK_URL = ""
            results = await send_webhook_alerts(
                mock_project, high_score_breakdown, "immediate_alert", "test"
            )
            assert results == {}

    @pytest.mark.asyncio
    async def test_both_webhooks_configured(self, mock_project, high_score_breakdown, mock_config):
        with patch("app.alerts.webhooks.settings") as mock_settings, \
             patch("app.alerts.webhooks.send_discord_alert", return_value=True) as mock_discord, \
             patch("app.alerts.webhooks.send_slack_alert", return_value=True) as mock_slack:
            mock_settings.DISCORD_WEBHOOK_URL = "https://discord.com/api/webhooks/test"
            mock_settings.SLACK_WEBHOOK_URL = "https://hooks.slack.com/services/test"
            results = await send_webhook_alerts(
                mock_project, high_score_breakdown, "immediate_alert", "test"
            )
            assert results["discord"] is True
            assert results["slack"] is True
            mock_discord.assert_awaited_once()
            mock_slack.assert_awaited_once()
