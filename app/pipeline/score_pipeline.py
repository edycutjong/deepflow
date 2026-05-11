"""
Score pipeline — orchestrates full scoring run.
1. Compute TVL growth_30d from TvlSnapshot history
2. Gather VC funding + GitHub signals per project
3. Run scoring engine
4. Save ScoreHistory with full breakdown
5. Update Project.latest_score
6. Trigger alert evaluation
"""
import json
from datetime import datetime, timedelta, timezone
from typing import Any

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.alerts.telegram import evaluate_and_alert, flush_queued_alerts
from app.core.scoring import ScoreBreakdown, generate_score
from app.db.models import (
    FundingRound,
    GithubSignal,
    Project,
    ScoreHistory,
    TvlSnapshot,
)


async def _compute_tvl_growth(
    session: AsyncSession, project_id: int, now: datetime
) -> float:
    """Calculate 30-day TVL growth percentage from snapshots."""
    current_result = await session.execute(
        select(TvlSnapshot.tvl_usd)
        .where(TvlSnapshot.project_id == project_id)
        .order_by(TvlSnapshot.recorded_at.desc())
        .limit(1)
    )
    current_tvl = current_result.scalar_one_or_none()

    if current_tvl is None or current_tvl <= 0:
        return 0.0

    thirty_days_ago = now - timedelta(days=30)
    past_result = await session.execute(
        select(TvlSnapshot.tvl_usd)
        .where(TvlSnapshot.project_id == project_id)
        .where(TvlSnapshot.recorded_at <= thirty_days_ago)
        .order_by(TvlSnapshot.recorded_at.desc())
        .limit(1)
    )
    past_tvl = past_result.scalar_one_or_none()

    if past_tvl is None or past_tvl <= 0:
        return 0.0

    return ((current_tvl - past_tvl) / past_tvl) * 100.0


async def _gather_vcs(
    session: AsyncSession, project_id: int
) -> tuple[list[dict[str, Any]], datetime | None]:
    """Get VC investors and latest funding round date for a project."""
    result = await session.execute(
        select(FundingRound)
        .where(FundingRound.project_id == project_id)
        .order_by(FundingRound.round_date.desc())
    )
    rounds = result.scalars().all()

    if not rounds:
        return [], None

    vcs: list[dict[str, Any]] = []
    latest_date: datetime | None = None

    for fr in rounds:
        if fr.round_date and (latest_date is None or fr.round_date > latest_date):
            latest_date = fr.round_date

        if fr.lead_investor:
            vcs.append({"name": fr.lead_investor})

        if fr.investors:
            try:
                investor_list = json.loads(fr.investors)
                for inv in investor_list:
                    if isinstance(inv, str):
                        vcs.append({"name": inv})
            except (json.JSONDecodeError, TypeError):
                pass

    # Deduplicate by name
    seen = set()
    unique_vcs = []
    for vc in vcs:
        if vc["name"] not in seen:
            seen.add(vc["name"])
            unique_vcs.append(vc)

    return unique_vcs, latest_date


async def _gather_github_hits(
    session: AsyncSession, project_id: int
) -> list[dict[str, Any]]:
    """Get GitHub signals for a project, respecting override false positives."""
    result = await session.execute(
        select(GithubSignal).where(GithubSignal.project_id == project_id)
    )
    signals = result.scalars().all()

    return [
        {
            "keyword": s.keyword,
            "date": s.commit_date,
            "hash": s.commit_hash,
            "is_false_positive": s.is_false_positive,
        }
        for s in signals
    ]


async def score_project(
    session: AsyncSession, project: Project, now: datetime | None = None
) -> ScoreBreakdown:
    """Score a single project and persist results."""
    if now is None:
        now = datetime.now(timezone.utc)

    # Gather inputs
    growth_pct = await _compute_tvl_growth(session, project.id, now)
    vcs, funding_date = await _gather_vcs(session, project.id)
    github_hits = await _gather_github_hits(session, project.id)

    tvl_usd = project.current_tvl or 0.0

    # Run scoring engine
    breakdown = generate_score(
        tvl_usd=tvl_usd,
        growth_30d_pct=growth_pct,
        vcs=vcs,
        funding_round_date=funding_date,
        github_hits=github_hits,
        now=now,
    )

    # Persist score history
    history = ScoreHistory(
        project_id=project.id,
        total_score=breakdown.total_score,
        tvl_points=breakdown.tvl_points,
        growth_points=breakdown.growth_points,
        funding_points=breakdown.funding_points,
        github_points=breakdown.github_points,
        breakdown_json=json.dumps(
            {
                "funding_details": breakdown.funding_details,
                "github_details": breakdown.github_details,
                "decay_multipliers": breakdown.decay_multipliers_applied,
            }
        ),
    )
    session.add(history)

    # Update project latest score + growth
    project.latest_score = breakdown.total_score
    project.tvl_growth_30d_pct = growth_pct

    await session.flush()

    return breakdown


async def run_scoring_pipeline(session: AsyncSession) -> int:
    """
    Full scoring pipeline: score all projects, evaluate alerts, flush queue.
    Returns the number of projects scored.
    """
    now = datetime.now(timezone.utc)

    result = await session.execute(select(Project))
    projects = result.scalars().all()

    scored = 0
    for project in projects:
        try:
            breakdown = await score_project(session, project, now)
            await evaluate_and_alert(session, project, breakdown, now)
            scored += 1
        except Exception as e:
            logger.error(f"Failed to score {project.slug}: {e}")
            await session.rollback()

    await session.commit()

    # Flush any alerts that were queued during quiet hours
    await flush_queued_alerts(session)

    logger.info(f"Scoring pipeline complete: {scored}/{len(projects)} projects scored")
    return scored
