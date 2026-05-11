"""
Tests for Telegram alerting — quiet hours, dedup, threshold routing.
"""
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.alerts.telegram import (
    _is_quiet_hours,
    _is_duplicate_alert,
    evaluate_and_alert,
    flush_queued_alerts,
)
from app.core.scoring import ScoreBreakdown
from app.db.models import AlertQueue, Project


class TestQuietHours:
    """Tests for quiet hours enforcement (23:00 - 07:00 Asia/Jakarta)."""

    def test_midnight_is_quiet(self, mock_config):
        # Midnight UTC = 07:00 WIB, but 23:00 UTC = 06:00 WIB (next day)
        # Jakarta is UTC+7, so 00:00 WIB = 17:00 UTC
        # 00:00 WIB is within 23:00-07:00 quiet window
        midnight_jakarta = datetime(2026, 1, 15, 17, 0, 0, tzinfo=timezone.utc)
        assert _is_quiet_hours(midnight_jakarta) is True

    def test_noon_is_not_quiet(self, mock_config):
        # 12:00 WIB = 05:00 UTC
        noon_jakarta = datetime(2026, 1, 15, 5, 0, 0, tzinfo=timezone.utc)
        assert _is_quiet_hours(noon_jakarta) is False

    def test_2300_jakarta_is_quiet(self, mock_config):
        # 23:00 WIB = 16:00 UTC
        start_quiet = datetime(2026, 1, 15, 16, 0, 0, tzinfo=timezone.utc)
        assert _is_quiet_hours(start_quiet) is True

    def test_0700_jakarta_is_not_quiet(self, mock_config):
        # 07:00 WIB = 00:00 UTC
        end_quiet = datetime(2026, 1, 15, 0, 0, 0, tzinfo=timezone.utc)
        assert _is_quiet_hours(end_quiet) is False


class TestDeduplication:
    @pytest.mark.asyncio
    async def test_no_previous_alert_is_not_duplicate(self, mock_config):
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        assert await _is_duplicate_alert(mock_session, 1, 80.0) is False

    @pytest.mark.asyncio
    async def test_similar_score_is_duplicate(self, mock_config):
        mock_session = AsyncMock()
        last_alert = MagicMock()
        last_alert.score_at_alert = 78.0  # Within delta of 10

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = last_alert
        mock_session.execute.return_value = mock_result

        # 80.0 - 78.0 = 2.0, which is < alert_dedup_delta (10)
        assert await _is_duplicate_alert(mock_session, 1, 80.0) is True

    @pytest.mark.asyncio
    async def test_different_score_is_not_duplicate(self, mock_config):
        mock_session = AsyncMock()
        last_alert = MagicMock()
        last_alert.score_at_alert = 60.0

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = last_alert
        mock_session.execute.return_value = mock_result

        # 80.0 - 60.0 = 20.0, which is >= alert_dedup_delta (10)
        assert await _is_duplicate_alert(mock_session, 1, 80.0) is False


class TestEvaluateAndAlert:
    @pytest.mark.asyncio
    async def test_below_watchlist_no_alert(self, mock_config):
        mock_session = AsyncMock()
        project = MagicMock(spec=Project)
        project.id = 1
        project.name = "LowScore"

        breakdown = ScoreBreakdown(total_score=30.0)

        # Should not add any alert
        await evaluate_and_alert(mock_session, project, breakdown)
        mock_session.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_above_immediate_triggers_alert(self, mock_config):
        mock_session = AsyncMock()

        # Mock dedup check to return no previous alert
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        project = MagicMock(spec=Project)
        project.id = 1
        project.name = "HighScore"

        breakdown = ScoreBreakdown(total_score=80.0)

        # Use non-quiet hours (10:00 WIB = 03:00 UTC)
        now = datetime(2026, 1, 15, 3, 0, 0, tzinfo=timezone.utc)

        with patch("app.alerts.telegram.send_telegram_alert", return_value=True) as mock_send:
            await evaluate_and_alert(mock_session, project, breakdown, now)
            mock_send.assert_awaited_once()

        mock_session.add.assert_called_once()
