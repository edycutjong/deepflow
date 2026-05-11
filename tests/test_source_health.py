"""
Tests for source health monitoring — failure tracking, auto-disable, digest.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock

from app.core.source_health import (
    MAX_CONSECUTIVE_FAILURES,
    record_success,
    record_failure,
    is_source_healthy,
    re_enable_source,
    get_health_digest,
)
from app.db.models import SourceHealth


def _make_mock_session(existing_health=None):
    """Create a mock async session that returns an optional SourceHealth."""
    session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = existing_health
    session.execute.return_value = mock_result
    return session


class TestRecordSuccess:
    @pytest.mark.asyncio
    async def test_resets_failure_counter(self):
        health = SourceHealth(
            source_name="defillama",
            consecutive_failures=3,
            is_healthy=True,
            last_error="timeout",
        )
        session = _make_mock_session(health)

        await record_success(session, "defillama")

        assert health.consecutive_failures == 0
        assert health.is_healthy is True
        assert health.last_error is None
        assert health.last_success is not None
        session.commit.assert_awaited()

    @pytest.mark.asyncio
    async def test_re_enables_disabled_source(self):
        health = SourceHealth(
            source_name="github",
            consecutive_failures=5,
            is_healthy=False,
        )
        session = _make_mock_session(health)

        await record_success(session, "github")

        assert health.is_healthy is True
        assert health.consecutive_failures == 0


class TestRecordFailure:
    @pytest.mark.asyncio
    async def test_increments_failure_count(self):
        health = SourceHealth(
            source_name="funding",
            consecutive_failures=0,
            is_healthy=True,
        )
        session = _make_mock_session(health)

        disabled = await record_failure(session, "funding", "connection refused")

        assert health.consecutive_failures == 1
        assert health.is_healthy is True
        assert disabled is False

    @pytest.mark.asyncio
    async def test_auto_disables_after_max_failures(self):
        health = SourceHealth(
            source_name="defillama",
            consecutive_failures=MAX_CONSECUTIVE_FAILURES - 1,
            is_healthy=True,
        )
        session = _make_mock_session(health)

        disabled = await record_failure(session, "defillama", "500 server error")

        assert health.consecutive_failures == MAX_CONSECUTIVE_FAILURES
        assert health.is_healthy is False
        assert disabled is True

    @pytest.mark.asyncio
    async def test_already_disabled_no_double_log(self):
        health = SourceHealth(
            source_name="github",
            consecutive_failures=10,
            is_healthy=False,
        )
        session = _make_mock_session(health)

        disabled = await record_failure(session, "github", "rate limited")

        assert health.consecutive_failures == 11
        assert disabled is False  # Already disabled, no new disable event

    @pytest.mark.asyncio
    async def test_truncates_long_error(self):
        health = SourceHealth(
            source_name="test",
            consecutive_failures=0,
            is_healthy=True,
        )
        session = _make_mock_session(health)

        long_error = "x" * 2000
        await record_failure(session, "test", long_error)

        assert health.last_error is not None
        assert len(health.last_error) == 1000


class TestIsSourceHealthy:
    @pytest.mark.asyncio
    async def test_unknown_source_is_healthy(self):
        session = _make_mock_session(None)  # Source doesn't exist

        result = await is_source_healthy(session, "new_source")
        assert result is True

    @pytest.mark.asyncio
    async def test_disabled_source_is_not_healthy(self):
        health = SourceHealth(source_name="broken", is_healthy=False)
        session = _make_mock_session(health)

        result = await is_source_healthy(session, "broken")
        assert result is False


class TestReEnableSource:
    @pytest.mark.asyncio
    async def test_re_enable_resets_state(self):
        health = SourceHealth(
            source_name="github",
            is_healthy=False,
            consecutive_failures=7,
            last_error="rate limited",
        )
        session = _make_mock_session(health)

        result = await re_enable_source(session, "github")

        assert result is True
        assert health.is_healthy is True
        assert health.consecutive_failures == 0

    @pytest.mark.asyncio
    async def test_re_enable_unknown_returns_false(self):
        session = _make_mock_session(None)

        result = await re_enable_source(session, "nonexistent")
        assert result is False


class TestHealthDigest:
    @pytest.mark.asyncio
    async def test_empty_digest(self):
        session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        session.execute.return_value = mock_result

        digest = await get_health_digest(session)
        assert "No sources tracked" in digest

    @pytest.mark.asyncio
    async def test_digest_with_mixed_health(self):
        from datetime import datetime, timezone

        healthy = SourceHealth(
            source_name="defillama",
            is_healthy=True,
            consecutive_failures=0,
            last_success=datetime(2026, 5, 10, tzinfo=timezone.utc),
        )
        unhealthy = SourceHealth(
            source_name="github",
            is_healthy=False,
            consecutive_failures=5,
            last_success=datetime(2026, 5, 8, tzinfo=timezone.utc),
            last_error="rate limited",
        )

        session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [healthy, unhealthy]
        session.execute.return_value = mock_result

        digest = await get_health_digest(session)

        assert "✅" in digest
        assert "❌" in digest
        assert "defillama" in digest
        assert "github" in digest
        assert "1/2 sources healthy" in digest
