"""
DefiLlama async scraper.
- httpx + tenacity retry (fail fast on 4xx, retry on 5xx)
- ON CONFLICT DO UPDATE upserts
- Batched TVL backfill
"""
import httpx
from loguru import logger
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from app.core.metrics_collector import MetricsCollector

DEFILLAMA_BASE = "https://api.llama.fi"
TVL_THRESHOLD = 1_000_000  # $1M minimum


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code >= 500
    return isinstance(exc, (httpx.ConnectTimeout, httpx.ReadTimeout))


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    retry=retry_if_exception(_is_retryable),
    reraise=True,
)
async def fetch_json_with_retry(
    client: httpx.AsyncClient, url: str
) -> tuple[dict, int]:
    resp = await client.get(url, timeout=30.0)
    resp.raise_for_status()
    return resp.json(), resp.status_code


async def scrape_protocols(session: AsyncSession) -> None:
    """Fetch all DefiLlama protocols, filter tokenless above TVL threshold, upsert."""
    async with MetricsCollector("defillama", session) as m:
        async with httpx.AsyncClient() as client:
            m.api_calls_made += 1
            data, _ = await fetch_json_with_retry(
                client, f"{DEFILLAMA_BASE}/protocols"
            )

            protocols = [
                p
                for p in data
                if p.get("category") != "CEX"
                and (not p.get("symbol") or p.get("symbol") == "-")
                and p.get("tvl", 0) > TVL_THRESHOLD
            ]

            logger.info(
                f"Filtered {len(protocols)} tokenless protocols above "
                f"${TVL_THRESHOLD:,}"
            )

            for p in protocols:
                await session.execute(
                    text("""
                        INSERT INTO projects (slug, name, category, has_token, current_tvl)
                        VALUES (:slug, :name, :category, :has_token, :tvl)
                        ON CONFLICT (slug) DO UPDATE SET
                            name = EXCLUDED.name,
                            category = EXCLUDED.category,
                            current_tvl = EXCLUDED.current_tvl,
                            last_updated = NOW()
                    """),
                    {
                        "slug": p["slug"],
                        "name": p["name"],
                        "category": p.get("category"),
                        "has_token": False,
                        "tvl": p.get("tvl", 0),
                    },
                )
                m.projects_upserted += 1

            await session.commit()


async def backfill_tvl_history(
    session: AsyncSession, slugs: list[str] | None = None
) -> None:
    """Batched TVL history backfill from DefiLlama /protocol/{slug} endpoint."""
    async with MetricsCollector("defillama_tvl_backfill", session) as m:
        if slugs is None:
            result = await session.execute(text("SELECT slug FROM projects"))
            slugs = [row[0] for row in result.fetchall()]

        async with httpx.AsyncClient() as client:
            for slug in slugs:
                try:
                    m.api_calls_made += 1
                    data, _ = await fetch_json_with_retry(
                        client, f"{DEFILLAMA_BASE}/protocol/{slug}"
                    )

                    tvl_history = data.get("tvl", [])
                    if not tvl_history:
                        continue

                    for point in tvl_history:
                        await session.execute(
                            text("""
                                INSERT INTO tvl_snapshots
                                    (project_id, tvl_usd, recorded_at)
                                SELECT p.id, :tvl, to_timestamp(:ts)
                                FROM projects p WHERE p.slug = :slug
                                ON CONFLICT DO NOTHING
                            """),
                            {
                                "slug": slug,
                                "tvl": point.get("totalLiquidityUSD", 0),
                                "ts": point["date"],
                            },
                        )
                        m.records_inserted += 1

                    await session.commit()
                    logger.debug(
                        f"Backfilled {len(tvl_history)} TVL points for {slug}"
                    )

                except Exception as e:
                    m.api_errors += 1
                    logger.warning(f"Failed to backfill TVL for {slug}: {e}")
                    await session.rollback()
