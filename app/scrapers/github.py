"""
GitHub commit keyword scanner.
- Fetches GitHub repo URLs from DefiLlama protocol data
- Scans recent commits for configured keywords (tge, airdrop, etc.)
- Populates github_signals table with dedup via unique constraint
- Respects github_overrides for false positive suppression
"""
import json
from datetime import datetime, timedelta, timezone

import httpx
from loguru import logger
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.config_loader import get_config
from app.core.metrics_collector import MetricsCollector
from app.db.models import GithubOverride, Project

GITHUB_API = "https://api.github.com"


def _github_headers() -> dict[str, str]:
    """Build GitHub API headers, with optional auth token."""
    headers = {"Accept": "application/vnd.github.v3+json"}
    if settings.GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {settings.GITHUB_TOKEN}"
    return headers


def _parse_github_org_repo(url: str) -> tuple[str, str] | None:
    """Parse 'https://github.com/org/repo' into (org, repo)."""
    url = url.rstrip("/")
    parts = url.split("github.com/")
    if len(parts) != 2:
        return None
    path = parts[1].split("/")
    if len(path) >= 2:
        return path[0], path[1]
    # Org-level URL — will need to list repos
    if len(path) == 1 and path[0]:
        return path[0], ""
    return None


async def _get_github_urls(
    client: httpx.AsyncClient, slug: str
) -> list[str]:
    """Extract GitHub repo/org URLs from DefiLlama protocol data."""
    try:
        resp = await client.get(
            f"https://api.llama.fi/protocol/{slug}", timeout=30.0
        )
        if resp.status_code != 200:
            return []
        data = resp.json()

        github_urls = data.get("github", [])
        if isinstance(github_urls, list):
            return github_urls

        # Fallback: check openSource / url fields
        url = data.get("url", "")
        if "github.com" in url:
            return [url]

        return []
    except Exception:
        return []


async def _list_org_repos(
    client: httpx.AsyncClient, org: str, max_repos: int = 5
) -> list[str]:
    """List top repos for a GitHub org (sorted by push date)."""
    try:
        resp = await client.get(
            f"{GITHUB_API}/orgs/{org}/repos",
            params={"sort": "pushed", "per_page": max_repos},
            headers=_github_headers(),
            timeout=30.0,
        )
        if resp.status_code != 200:
            return []
        return [r["full_name"] for r in resp.json() if not r.get("fork")]
    except Exception:
        return []


async def _scan_repo_commits(
    client: httpx.AsyncClient,
    owner: str,
    repo: str,
    keywords: list[str],
    since_days: int = 90,
) -> list[dict]:
    """Scan recent commits in a repo for keyword matches."""
    since = datetime.now(timezone.utc) - timedelta(days=since_days)
    since_str = since.strftime("%Y-%m-%dT%H:%M:%SZ")

    signals: list[dict] = []
    page = 1

    while page <= 3:  # Cap at 3 pages (90 commits max)
        resp = await client.get(
            f"{GITHUB_API}/repos/{owner}/{repo}/commits",
            params={"since": since_str, "per_page": 30, "page": page},
            headers=_github_headers(),
            timeout=30.0,
        )

        if resp.status_code == 404:
            break
        if resp.status_code == 409:
            # Empty repo
            break
        resp.raise_for_status()

        commits = resp.json()
        if not commits:
            break

        for commit in commits:
            message = (
                commit.get("commit", {}).get("message", "") or ""
            ).lower()
            sha = commit.get("sha", "")
            date_str = (
                commit.get("commit", {})
                .get("author", {})
                .get("date", "")
            )

            for kw in keywords:
                if kw.lower() in message:
                    try:
                        commit_date = datetime.fromisoformat(
                            date_str.replace("Z", "+00:00")
                        )
                    except (ValueError, TypeError):
                        commit_date = datetime.now(timezone.utc)

                    signals.append(
                        {
                            "keyword": kw.lower(),
                            "commit_hash": sha[:40],
                            "commit_date": commit_date,
                            "commit_message": commit.get("commit", {}).get(
                                "message", ""
                            )[:500],
                            "repo_url": f"https://github.com/{owner}/{repo}",
                        }
                    )

        page += 1

    return signals


async def scan_project_github(
    session: AsyncSession,
    project: Project,
    client: httpx.AsyncClient,
) -> int:
    """Scan a single project's GitHub repos for keyword signals.
    Returns count of new signals."""
    cfg = get_config().scoring.github
    keywords = list(cfg.keyword_hits.keys())

    if not keywords:
        return 0

    # Get GitHub repos for this project
    github_urls = await _get_github_urls(client, project.slug)
    if not github_urls:
        return 0

    # Load existing overrides for this project
    override_result = await session.execute(
        select(GithubOverride).where(GithubOverride.project_id == project.id)
    )
    overrides = {
        (o.commit_hash, o.keyword): o.is_false_positive
        for o in override_result.scalars().all()
    }

    new_signals = 0

    for url in github_urls:
        parsed = _parse_github_org_repo(url)
        if not parsed:
            continue
        org, repo_name = parsed

        # If org-level URL, list top repos
        if not repo_name:
            full_names = await _list_org_repos(client, org)
            repo_pairs = [fn.split("/", 1) for fn in full_names]
        else:
            repo_pairs = [(org, repo_name)]

        for owner, repo in repo_pairs:
            try:
                signals = await _scan_repo_commits(
                    client, owner, repo, keywords
                )

                for sig in signals:
                    # Check override
                    is_fp = overrides.get(
                        (sig["commit_hash"], sig["keyword"]), False
                    )

                    await session.execute(
                        text("""
                            INSERT INTO github_signals
                                (project_id, repo_url, keyword, commit_hash,
                                 commit_date, commit_message, is_false_positive)
                            VALUES
                                (:pid, :repo, :kw, :hash, :date, :msg, :fp)
                            ON CONFLICT ON CONSTRAINT uq_github_signal
                            DO UPDATE SET
                                commit_message = EXCLUDED.commit_message,
                                is_false_positive = EXCLUDED.is_false_positive
                        """),
                        {
                            "pid": project.id,
                            "repo": sig["repo_url"],
                            "kw": sig["keyword"],
                            "hash": sig["commit_hash"],
                            "date": sig["commit_date"],
                            "msg": sig["commit_message"],
                            "fp": is_fp,
                        },
                    )
                    new_signals += 1

            except httpx.HTTPStatusError as e:
                if e.response.status_code == 403:
                    logger.warning(
                        f"GitHub rate limited scanning {owner}/{repo}"
                    )
                    return new_signals  # Stop entirely on rate limit
                logger.warning(f"GitHub API error for {owner}/{repo}: {e}")
            except Exception as e:
                logger.warning(f"Failed to scan {owner}/{repo}: {e}")

    return new_signals


async def scrape_github_signals(session: AsyncSession) -> None:
    """Scan all projects for GitHub keyword signals."""
    async with MetricsCollector("github_signals", session) as m:
        result = await session.execute(select(Project))
        projects = result.scalars().all()

        async with httpx.AsyncClient() as client:
            for project in projects:
                try:
                    count = await scan_project_github(
                        session, project, client
                    )
                    m.records_inserted += count
                    if count > 0:
                        logger.info(
                            f"Found {count} GitHub signals for {project.name}"
                        )
                except Exception as e:
                    m.api_errors += 1
                    logger.error(
                        f"GitHub scan failed for {project.slug}: {e}"
                    )
                    await session.rollback()

        await session.commit()
        logger.info(
            f"GitHub scan complete: {m.records_inserted} signals across "
            f"{len(projects)} projects"
        )
