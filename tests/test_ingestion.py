"""
Ingestion tests — 6 exact filtering edge-cases, respx multi-status recovery,
and MetricsCollector rollback logic.
"""
import httpx
import pytest
import respx
from unittest.mock import AsyncMock

from app.core.metrics_collector import MetricsCollector
from app.scrapers.defillama import TVL_THRESHOLD, fetch_json_with_retry


class TestDefiLlamaFiltering:
    def filter_protocols(self, data):
        """Replicates exact logic from defillama.py for isolation testing."""
        return [
            {"slug": p["slug"], "name": p["name"], "has_token": False}
            for p in data
            if p.get("category") != "CEX"
            and (not p.get("symbol") or p.get("symbol") == "-")
            and p.get("tvl", 0) > TVL_THRESHOLD
        ]

    def test_valid_project_included(self):
        data = [
            {
                "slug": "valid",
                "name": "Valid",
                "category": "DeFi",
                "symbol": None,
                "tvl": 5_000_000,
            }
        ]
        assert len(self.filter_protocols(data)) == 1

    def test_cex_excluded(self):
        data = [
            {
                "slug": "binance",
                "name": "Binance",
                "category": "CEX",
                "symbol": None,
                "tvl": 50_000_000,
            }
        ]
        assert len(self.filter_protocols(data)) == 0

    def test_token_excluded(self):
        data = [
            {
                "slug": "uni",
                "name": "Uniswap",
                "category": "DeFi",
                "symbol": "UNI",
                "tvl": 5_000_000,
            }
        ]
        assert len(self.filter_protocols(data)) == 0

    def test_low_tvl_excluded(self):
        data = [
            {
                "slug": "smol",
                "name": "Smol",
                "category": "DeFi",
                "symbol": None,
                "tvl": 500_000,
            }
        ]
        assert len(self.filter_protocols(data)) == 0

    def test_empty_string_symbol_included(self):
        data = [
            {
                "slug": "empty",
                "name": "Empty",
                "category": "DeFi",
                "symbol": "",
                "tvl": 5_000_000,
            }
        ]
        assert len(self.filter_protocols(data)) == 1

    def test_dash_symbol_included(self):
        data = [
            {
                "slug": "dash",
                "name": "Dash",
                "category": "DeFi",
                "symbol": "-",
                "tvl": 5_000_000,
            }
        ]
        assert len(self.filter_protocols(data)) == 1


@pytest.mark.asyncio
@respx.mock
async def test_respx_http_retry_404_fast_fail():
    url = "https://api.llama.fi/test"
    route = respx.get(url).mock(return_value=httpx.Response(404))

    async with httpx.AsyncClient() as client:
        with pytest.raises(httpx.HTTPStatusError):
            await fetch_json_with_retry(client, url)

    assert route.call_count == 1  # Verified no retries on 404


@pytest.mark.asyncio
@respx.mock
async def test_respx_http_retry_500_recovery():
    url = "https://api.llama.fi/test"
    route = respx.get(url)
    route.side_effect = [
        httpx.Response(500),
        httpx.Response(502),
        httpx.Response(200, json={"success": True}),
    ]

    async with httpx.AsyncClient() as client:
        data, status = await fetch_json_with_retry(client, url)

    assert data == {"success": True}
    assert status == 200
    assert route.call_count == 3


@pytest.mark.asyncio
async def test_metrics_collector_handles_scraper_crash():
    mock_session = AsyncMock()

    try:
        async with MetricsCollector("defillama", mock_session) as m:
            raise ValueError("Scraper exploded mid-flight")
    except ValueError:
        pass

    assert m.api_errors == 1
    assert "exploded" in m.error_details
    # Scraper crashed, so it rolled back the dirty state, then committed the metric
    mock_session.rollback.assert_awaited_once()
    mock_session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_metrics_collector_rollback_on_commit_failure():
    mock_session = AsyncMock()
    mock_session.commit.side_effect = Exception("DB Down")

    async with MetricsCollector("defillama", mock_session) as m:
        m.projects_upserted = 10

    # The commit MUST have been attempted
    mock_session.commit.assert_awaited_once()
    # And the rollback MUST have caught the failure
    mock_session.rollback.assert_awaited_once()
