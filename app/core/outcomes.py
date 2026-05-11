"""
Outcome Tracking — CLI-style functions for recording project outcomes
and backtesting model accuracy.
"""
from datetime import datetime, timezone

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Project, ProjectOutcome

# Valid outcome types
VALID_OUTCOMES = {
    "tge_launched",
    "airdrop_confirmed",
    "airdrop_rumor",
    "rug",
    "abandoned",
    "still_building",
}


async def record_outcome(
    session: AsyncSession,
    slug: str,
    outcome_type: str,
    notes: str | None = None,
    outcome_date: datetime | None = None,
) -> ProjectOutcome | None:
    """
    Record a project outcome for backtesting.
    Captures the project's score at the time of recording.
    Returns the created ProjectOutcome or None if project not found.
    """
    if outcome_type not in VALID_OUTCOMES:
        raise ValueError(
            f"Invalid outcome_type: '{outcome_type}'. "
            f"Must be one of: {sorted(VALID_OUTCOMES)}"
        )

    # Find project
    result = await session.execute(
        select(Project).where(Project.slug == slug)
    )
    project = result.scalar_one_or_none()

    if project is None:
        logger.warning(f"Project not found: {slug}")
        return None

    if outcome_date is None:
        outcome_date = datetime.now(timezone.utc)

    outcome = ProjectOutcome(
        project_id=project.id,
        outcome_type=outcome_type,
        outcome_date=outcome_date,
        notes=notes,
        score_at_outcome=project.latest_score,
    )
    session.add(outcome)
    await session.commit()

    logger.info(
        f"Outcome recorded: {slug} → {outcome_type} "
        f"(score={project.latest_score})"
    )
    return outcome


async def get_accuracy_report(session: AsyncSession) -> dict:
    """
    Generate a model accuracy report by comparing scores at outcome time
    against actual outcomes.

    Returns a dict with:
    - total_outcomes: total recorded outcomes
    - by_type: count per outcome type
    - avg_score_by_type: average score at outcome per type
    - hit_rate: % of positive outcomes (tge/airdrop) that had score >= 50
    - false_positive_rate: % of rug/abandoned with score >= 50
    """
    result = await session.execute(
        select(ProjectOutcome).order_by(ProjectOutcome.outcome_date)
    )
    outcomes = result.scalars().all()

    if not outcomes:
        return {
            "total_outcomes": 0,
            "by_type": {},
            "avg_score_by_type": {},
            "hit_rate": None,
            "false_positive_rate": None,
        }

    by_type: dict[str, int] = {}
    scores_by_type: dict[str, list[float]] = {}

    for o in outcomes:
        by_type[o.outcome_type] = by_type.get(o.outcome_type, 0) + 1
        if o.score_at_outcome is not None:
            if o.outcome_type not in scores_by_type:
                scores_by_type[o.outcome_type] = []
            scores_by_type[o.outcome_type].append(o.score_at_outcome)

    avg_score_by_type = {
        k: round(sum(v) / len(v), 1) if v else 0
        for k, v in scores_by_type.items()
    }

    # Calculate hit rate: positive outcomes with score >= 50
    positive_types = {"tge_launched", "airdrop_confirmed"}
    positive_outcomes = [
        o for o in outcomes if o.outcome_type in positive_types
    ]
    if positive_outcomes:
        hits = sum(
            1
            for o in positive_outcomes
            if o.score_at_outcome is not None and o.score_at_outcome >= 50
        )
        hit_rate = round(hits / len(positive_outcomes) * 100, 1)
    else:
        hit_rate = None

    # Calculate false positive rate: negative outcomes with score >= 50
    negative_types = {"rug", "abandoned"}
    negative_outcomes = [
        o for o in outcomes if o.outcome_type in negative_types
    ]
    if negative_outcomes:
        false_positives = sum(
            1
            for o in negative_outcomes
            if o.score_at_outcome is not None and o.score_at_outcome >= 50
        )
        false_positive_rate = round(
            false_positives / len(negative_outcomes) * 100, 1
        )
    else:
        false_positive_rate = None

    return {
        "total_outcomes": len(outcomes),
        "by_type": by_type,
        "avg_score_by_type": avg_score_by_type,
        "hit_rate": hit_rate,
        "false_positive_rate": false_positive_rate,
    }


def format_accuracy_report(report: dict) -> str:
    """Format the accuracy report for Telegram/CLI output."""
    if report["total_outcomes"] == 0:
        return "📉 *Model Accuracy*: No outcomes recorded yet."

    lines = [
        "📉 *Model Accuracy Report*",
        f"Total outcomes tracked: {report['total_outcomes']}",
        "",
        "*Outcomes by Type:*",
    ]

    for otype, count in sorted(report["by_type"].items()):
        avg = report["avg_score_by_type"].get(otype, "N/A")
        lines.append(f"  • {otype}: {count} (avg score: {avg})")

    lines.append("")

    if report["hit_rate"] is not None:
        lines.append(f"✅ Hit Rate (TGE/Airdrop ≥50): *{report['hit_rate']}%*")

    if report["false_positive_rate"] is not None:
        lines.append(
            f"⚠️ False Positive Rate (Rug/Abandoned ≥50): *{report['false_positive_rate']}%*"
        )

    return "\n".join(lines)
