"""
Tests for outcome tracking — recording, validation, accuracy reporting.
"""
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

from app.core.outcomes import (
    VALID_OUTCOMES,
    record_outcome,
    get_accuracy_report,
    format_accuracy_report,
)
from app.db.models import Project


def _make_mock_session(project=None):
    """Create a mock session with optional project lookup."""
    session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = project
    session.execute.return_value = mock_result
    return session


class TestRecordOutcome:
    @pytest.mark.asyncio
    async def test_valid_outcome_recorded(self):
        project = MagicMock(spec=Project)
        project.id = 1
        project.slug = "aave"
        project.latest_score = 72.5
        session = _make_mock_session(project)

        outcome = await record_outcome(
            session, "aave", "tge_launched", notes="Token launched on Ethereum"
        )

        assert outcome is not None
        assert outcome.outcome_type == "tge_launched"
        assert outcome.score_at_outcome == 72.5
        session.commit.assert_awaited()

    @pytest.mark.asyncio
    async def test_invalid_outcome_type_raises(self):
        session = _make_mock_session()

        with pytest.raises(ValueError, match="Invalid outcome_type"):
            await record_outcome(session, "aave", "invalid_type")

    @pytest.mark.asyncio
    async def test_project_not_found_returns_none(self):
        session = _make_mock_session(None)  # No project

        outcome = await record_outcome(session, "nonexistent", "rug")
        assert outcome is None

    @pytest.mark.asyncio
    async def test_all_valid_outcome_types(self):
        """All defined outcome types should be accepted."""
        for otype in VALID_OUTCOMES:
            project = MagicMock(spec=Project)
            project.id = 1
            project.latest_score = 50.0
            session = _make_mock_session(project)

            outcome = await record_outcome(session, "test", otype)
            assert outcome is not None
            assert outcome.outcome_type == otype


class TestAccuracyReport:
    @pytest.mark.asyncio
    async def test_empty_report(self):
        session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        session.execute.return_value = mock_result

        report = await get_accuracy_report(session)

        assert report["total_outcomes"] == 0
        assert report["hit_rate"] is None

    @pytest.mark.asyncio
    async def test_hit_rate_calculation(self):
        outcomes = [
            MagicMock(
                outcome_type="tge_launched",
                score_at_outcome=75.0,
                outcome_date=datetime(2026, 5, 1, tzinfo=timezone.utc),
            ),
            MagicMock(
                outcome_type="airdrop_confirmed",
                score_at_outcome=60.0,
                outcome_date=datetime(2026, 5, 2, tzinfo=timezone.utc),
            ),
            MagicMock(
                outcome_type="tge_launched",
                score_at_outcome=30.0,  # Below threshold
                outcome_date=datetime(2026, 5, 3, tzinfo=timezone.utc),
            ),
        ]

        session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = outcomes
        session.execute.return_value = mock_result

        report = await get_accuracy_report(session)

        assert report["total_outcomes"] == 3
        # 2 of 3 positive outcomes had score >= 50
        assert report["hit_rate"] == 66.7

    @pytest.mark.asyncio
    async def test_false_positive_rate(self):
        outcomes = [
            MagicMock(
                outcome_type="rug",
                score_at_outcome=65.0,  # False positive
                outcome_date=datetime(2026, 5, 1, tzinfo=timezone.utc),
            ),
            MagicMock(
                outcome_type="abandoned",
                score_at_outcome=20.0,  # Correctly low
                outcome_date=datetime(2026, 5, 2, tzinfo=timezone.utc),
            ),
        ]

        session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = outcomes
        session.execute.return_value = mock_result

        report = await get_accuracy_report(session)

        assert report["false_positive_rate"] == 50.0


class TestFormatReport:
    def test_empty_format(self):
        report = {
            "total_outcomes": 0,
            "by_type": {},
            "avg_score_by_type": {},
            "hit_rate": None,
            "false_positive_rate": None,
        }
        text = format_accuracy_report(report)
        assert "No outcomes recorded" in text

    def test_full_format(self):
        report = {
            "total_outcomes": 5,
            "by_type": {"tge_launched": 3, "rug": 2},
            "avg_score_by_type": {"tge_launched": 70.0, "rug": 40.0},
            "hit_rate": 80.0,
            "false_positive_rate": 25.0,
        }
        text = format_accuracy_report(report)

        assert "80.0%" in text
        assert "25.0%" in text
        assert "tge_launched: 3" in text
