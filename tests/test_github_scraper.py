"""
Tests for GitHub signal scraper — URL parsing, commit scanning, override handling.
"""
import httpx
import pytest
import respx
from unittest.mock import AsyncMock, MagicMock

from app.scrapers.github import (
    _parse_github_org_repo,
    _scan_repo_commits,
    scan_project_github,
)
from app.db.models import Project


class TestGitHubURLParsing:
    def test_full_repo_url(self):
        result = _parse_github_org_repo("https://github.com/aave/aave-v3-core")
        assert result == ("aave", "aave-v3-core")

    def test_trailing_slash(self):
        result = _parse_github_org_repo("https://github.com/aave/aave-v3-core/")
        assert result == ("aave", "aave-v3-core")

    def test_org_only_url(self):
        result = _parse_github_org_repo("https://github.com/aave")
        assert result == ("aave", "")

    def test_invalid_url(self):
        result = _parse_github_org_repo("https://example.com/foo")
        assert result is None

    def test_empty_path(self):
        result = _parse_github_org_repo("https://github.com/")
        assert result is None


class TestCommitScanning:
    @pytest.mark.asyncio
    @respx.mock
    async def test_keyword_match_found(self):
        route = respx.get(
            "https://api.github.com/repos/test-org/test-repo/commits"
        )
        route.side_effect = [
            httpx.Response(
                200,
                json=[
                    {
                        "sha": "abc123def456abc123def456abc123def456abcd",
                        "commit": {
                            "message": "prepare for TGE launch on mainnet",
                            "author": {"date": "2026-05-01T10:00:00Z"},
                        },
                    }
                ],
            ),
            httpx.Response(200, json=[]),  # page 2: empty stops pagination
        ]

        async with httpx.AsyncClient() as client:
            signals = await _scan_repo_commits(
                client, "test-org", "test-repo", ["tge", "airdrop"]
            )

        assert len(signals) == 1
        assert signals[0]["keyword"] == "tge"
        assert "abc123" in signals[0]["commit_hash"]

    @pytest.mark.asyncio
    @respx.mock
    async def test_no_keyword_match(self):
        respx.get(
            "https://api.github.com/repos/test-org/test-repo/commits"
        ).mock(
            return_value=httpx.Response(
                200,
                json=[
                    {
                        "sha": "deadbeef" * 5,
                        "commit": {
                            "message": "fix: resolve memory leak in pool",
                            "author": {"date": "2026-05-01T10:00:00Z"},
                        },
                    }
                ],
            )
        )

        async with httpx.AsyncClient() as client:
            signals = await _scan_repo_commits(
                client, "test-org", "test-repo", ["tge", "airdrop"]
            )

        assert len(signals) == 0

    @pytest.mark.asyncio
    @respx.mock
    async def test_404_repo_returns_empty(self):
        respx.get(
            "https://api.github.com/repos/ghost/missing/commits"
        ).mock(return_value=httpx.Response(404))

        async with httpx.AsyncClient() as client:
            signals = await _scan_repo_commits(
                client, "ghost", "missing", ["tge"]
            )

        assert len(signals) == 0

    @pytest.mark.asyncio
    @respx.mock
    async def test_multiple_keywords_in_same_commit(self):
        route = respx.get(
            "https://api.github.com/repos/test-org/test-repo/commits"
        )
        route.side_effect = [
            httpx.Response(
                200,
                json=[
                    {
                        "sha": "a" * 40,
                        "commit": {
                            "message": "TGE confirmed, airdrop snapshot done",
                            "author": {"date": "2026-05-01T10:00:00Z"},
                        },
                    }
                ],
            ),
            httpx.Response(200, json=[]),  # page 2: empty stops pagination
        ]

        async with httpx.AsyncClient() as client:
            signals = await _scan_repo_commits(
                client, "test-org", "test-repo", ["tge", "airdrop"]
            )

        assert len(signals) == 2
        keywords = {s["keyword"] for s in signals}
        assert keywords == {"tge", "airdrop"}


class TestScanProjectGithub:
    @pytest.mark.asyncio
    @respx.mock
    async def test_no_github_urls_returns_zero(self):
        # DefiLlama returns no github field
        respx.get("https://api.llama.fi/protocol/test-project").mock(
            return_value=httpx.Response(200, json={"name": "Test", "github": []})
        )

        mock_session = AsyncMock()
        project = MagicMock(spec=Project)
        project.id = 1
        project.slug = "test-project"
        project.name = "Test"

        async with httpx.AsyncClient() as client:
            count = await scan_project_github(mock_session, project, client)

        assert count == 0
