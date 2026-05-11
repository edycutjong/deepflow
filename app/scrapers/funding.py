"""
Funding round scraper from DefiLlama /raises endpoint.
- Fetches all known DeFi funding rounds
- Matches to existing projects by slug (defiLlamaId)
- Parses investor lists for tier_1/tier_2 VC matching
- Deduplicates by (project_id, round_type, round_date)
"""
import json
from datetime import datetime, timezone

import httpx
from loguru import logger
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.metrics_collector import MetricsCollector

DEFILLAMA_RAISES = "https://api.llama.fi/raises"


async def scrape_funding_rounds(session: AsyncSession) -> None:
    """Fetch all DefiLlama raises and upsert matched projects."""
    async with MetricsCollector("funding_rounds", session) as m:
        async with httpx.AsyncClient() as client:
            m.api_calls_made += 1
            resp = await client.get(DEFILLAMA_RAISES, timeout=60.0)
            resp.raise_for_status()
            data = resp.json()

            # DefiLlama returns {"raises": [...]} or a flat list
            raises = data.get("raises", data) if isinstance(data, dict) else data

            if not isinstance(raises, list):
                logger.error("Unexpected /raises response format")
                return

            logger.info(f"Fetched {len(raises)} funding rounds from DefiLlama")

            # Get all project slugs → IDs
            result = await session.execute(
                text("SELECT id, slug FROM projects")
            )
            slug_map = {row[1]: row[0] for row in result.fetchall()}

            matched = 0
            for r in raises:
                slug = r.get("defiLlamaId")
                if not slug or slug not in slug_map:
                    continue

                project_id = slug_map[slug]

                # Parse round date
                round_date = None
                if r.get("date"):
                    try:
                        round_date = datetime.fromtimestamp(
                            r["date"], tz=timezone.utc
                        )
                    except (ValueError, TypeError, OSError):
                        pass

                # Parse investors
                lead_investors = r.get("leadInvestors") or []
                other_investors = r.get("otherInvestors") or []
                all_investors = lead_investors + other_investors
                lead = lead_investors[0] if lead_investors else None

                # Parse amount
                amount = None
                raw_amount = r.get("amount")
                if raw_amount is not None:
                    try:
                        amount = float(raw_amount) * 1_000_000  # stored in $M
                    except (ValueError, TypeError):
                        pass

                round_type = r.get("round") or "unknown"

                # Dedup: skip if identical (project_id, round_type, round_date) exists
                await session.execute(
                    text("""
                        INSERT INTO funding_rounds
                            (project_id, round_date, amount_usd, round_type,
                             lead_investor, investors, source_url)
                        SELECT :pid, :date, :amount, :round, :lead, :investors, :source
                        WHERE NOT EXISTS (
                            SELECT 1 FROM funding_rounds
                            WHERE project_id = :pid
                              AND round_type = :round
                              AND (round_date = :date OR (round_date IS NULL AND :date IS NULL))
                        )
                    """),
                    {
                        "pid": project_id,
                        "date": round_date,
                        "amount": amount,
                        "round": round_type,
                        "lead": lead,
                        "investors": json.dumps(all_investors) if all_investors else None,
                        "source": r.get("source"),
                    },
                )
                m.records_inserted += 1
                matched += 1

            await session.commit()
            logger.info(
                f"Funding scrape complete: {matched} rounds matched to "
                f"{len(slug_map)} projects"
            )
