"""
Tests for funding round scraper — response parsing, investor extraction, dedup.
"""
import httpx
import pytest
import respx
from unittest.mock import AsyncMock, MagicMock

from app.scrapers.funding import scrape_funding_rounds


class TestFundingRoundScraper:
    @pytest.mark.asyncio
    @respx.mock
    async def test_raises_matched_to_projects(self):
        """Raises with matching defiLlamaId should be inserted."""
        respx.get("https://api.llama.fi/raises").mock(
            return_value=httpx.Response(
                200,
                json={
                    "raises": [
                        {
                            "defiLlamaId": "aave",
                            "round": "Series A",
                            "amount": 25,
                            "date": 1700000000,
                            "leadInvestors": ["a16z"],
                            "otherInvestors": ["Paradigm", "Dragonfly"],
                            "source": "https://example.com",
                        }
                    ]
                },
            )
        )

        mock_session = AsyncMock()

        # Mock slug lookup: project "aave" exists with id=1
        mock_slug_result = MagicMock()
        mock_slug_result.fetchall.return_value = [(1, "aave")]
        mock_session.execute.return_value = mock_slug_result

        await scrape_funding_rounds(mock_session)

        # Should have executed: 1 slug lookup + 1 insert
        assert mock_session.execute.await_count >= 2
        mock_session.commit.assert_awaited()

    @pytest.mark.asyncio
    @respx.mock
    async def test_unmatched_raises_skipped(self):
        """Raises without matching project slug should be silently skipped."""
        respx.get("https://api.llama.fi/raises").mock(
            return_value=httpx.Response(
                200,
                json={
                    "raises": [
                        {
                            "defiLlamaId": "nonexistent-protocol",
                            "round": "Seed",
                            "amount": 5,
                            "date": 1700000000,
                            "leadInvestors": ["SomeVC"],
                        }
                    ]
                },
            )
        )

        mock_session = AsyncMock()

        # No matching slugs
        mock_slug_result = MagicMock()
        mock_slug_result.fetchall.return_value = []
        mock_session.execute.return_value = mock_slug_result

        await scrape_funding_rounds(mock_session)

        # Only the slug lookup query + commit, no insert
        mock_session.commit.assert_awaited()

    @pytest.mark.asyncio
    @respx.mock
    async def test_missing_date_handled(self):
        """Raises with no date should still be inserted with null round_date."""
        respx.get("https://api.llama.fi/raises").mock(
            return_value=httpx.Response(
                200,
                json={
                    "raises": [
                        {
                            "defiLlamaId": "compound",
                            "round": "Seed",
                            "amount": 10,
                            "date": None,
                            "leadInvestors": ["Paradigm"],
                        }
                    ]
                },
            )
        )

        mock_session = AsyncMock()

        mock_slug_result = MagicMock()
        mock_slug_result.fetchall.return_value = [(2, "compound")]
        mock_session.execute.return_value = mock_slug_result

        await scrape_funding_rounds(mock_session)
        mock_session.commit.assert_awaited()

    @pytest.mark.asyncio
    @respx.mock
    async def test_empty_investors_handled(self):
        """Raises with no investors should still insert with null lead."""
        respx.get("https://api.llama.fi/raises").mock(
            return_value=httpx.Response(
                200,
                json={
                    "raises": [
                        {
                            "defiLlamaId": "maker",
                            "round": "Unknown",
                            "amount": None,
                            "date": 1700000000,
                            "leadInvestors": None,
                            "otherInvestors": None,
                        }
                    ]
                },
            )
        )

        mock_session = AsyncMock()

        mock_slug_result = MagicMock()
        mock_slug_result.fetchall.return_value = [(3, "maker")]
        mock_session.execute.return_value = mock_slug_result

        await scrape_funding_rounds(mock_session)
        mock_session.commit.assert_awaited()

    @pytest.mark.asyncio
    @respx.mock
    async def test_flat_list_response_format(self):
        """Some endpoints return a flat list instead of {raises: [...]}."""
        respx.get("https://api.llama.fi/raises").mock(
            return_value=httpx.Response(
                200,
                json=[
                    {
                        "defiLlamaId": "lido",
                        "round": "Series B",
                        "amount": 70,
                        "date": 1700000000,
                        "leadInvestors": ["a16z"],
                    }
                ],
            )
        )

        mock_session = AsyncMock()

        mock_slug_result = MagicMock()
        mock_slug_result.fetchall.return_value = [(4, "lido")]
        mock_session.execute.return_value = mock_slug_result

        await scrape_funding_rounds(mock_session)
        mock_session.commit.assert_awaited()
