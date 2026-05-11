"""
Multi-factor scoring engine with time-decay.
Uses transparent ScoreBreakdown dataclass and funding_round_date for decay.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.core.config_loader import get_config


@dataclass
class ScoreBreakdown:
    tvl_points: float = 0.0
    growth_points: float = 0.0
    funding_points: float = 0.0
    github_points: float = 0.0
    total_score: float = 0.0
    funding_details: str = "No Tier-1/2 VCs"
    github_details: Dict[str, str] = field(default_factory=dict)
    decay_multipliers_applied: Dict[str, float] = field(default_factory=dict)


def apply_gradient(
    value: float, min_val: float, max_val: float, max_pts: float
) -> float:
    if value <= min_val:
        return 0.0
    if value >= max_val:
        return max_pts
    return max_pts * ((value - min_val) / (max_val - min_val))


def apply_decay(
    points: float, days_old: float, half_life_days: Optional[int]
) -> float:
    if not half_life_days or days_old < 0:
        return points
    return points * (0.5 ** (days_old / half_life_days))


def generate_score(
    tvl_usd: float,
    growth_30d_pct: float,
    vcs: List[Dict[str, Any]],
    funding_round_date: Optional[datetime],
    github_hits: List[Dict[str, Any]],
    now: Optional[datetime] = None,
) -> ScoreBreakdown:
    if now is None:
        now = datetime.now(timezone.utc)

    cfg = get_config().scoring
    vc_tiers = get_config().vcs
    bdown = ScoreBreakdown()

    # 1. TVL & Growth
    bdown.tvl_points = round(
        apply_gradient(
            tvl_usd / 1e6, cfg.tvl.min_m, cfg.tvl.max_m, cfg.tvl.max_points
        ),
        2,
    )
    bdown.growth_points = round(
        apply_gradient(
            growth_30d_pct,
            cfg.tvl_growth_30d.min_pct,
            cfg.tvl_growth_30d.max_pct,
            cfg.tvl_growth_30d.max_points,
        ),
        2,
    )
    bdown.total_score += bdown.tvl_points + bdown.growth_points

    # 2. VC Sorting & Decay
    best_funding_pts = 0.0
    if vcs:
        scored_vcs = []
        for vc in vcs:
            if vc["name"] in vc_tiers.tier_1:
                scored_vcs.append(
                    {"name": vc["name"], "pts": cfg.funding.tier_1_base_pts}
                )
            elif vc["name"] in vc_tiers.tier_2:
                scored_vcs.append(
                    {"name": vc["name"], "pts": cfg.funding.tier_2_base_pts}
                )

        if scored_vcs:
            scored_vcs.sort(key=lambda x: (-x["pts"], x["name"]))
            raw_funding_pts = sum(
                vc["pts"] * (1.0 if idx == 0 else cfg.funding.co_lead_multiplier)
                for idx, vc in enumerate(scored_vcs)
            )
            raw_funding_pts = min(raw_funding_pts, cfg.funding.max_category_points)

            multiplier = 1.0
            if funding_round_date:
                days_old = (now - funding_round_date).total_seconds() / 86400.0
                multiplier = apply_decay(
                    1.0, days_old, cfg.funding.decay_half_life_days
                )

            best_funding_pts = raw_funding_pts * multiplier
            vc_names = [v["name"] for v in scored_vcs]
            bdown.decay_multipliers_applied["funding"] = round(multiplier, 3)
            date_str = (
                funding_round_date.strftime("%Y-%m-%d")
                if funding_round_date
                else "Unknown"
            )
            bdown.funding_details = (
                f"Leads: {', '.join(vc_names)} | "
                f"Raw: {raw_funding_pts} | "
                f"Decay: {round(multiplier, 2)}x | "
                f"Date: {date_str}"
            )

    bdown.funding_points = round(best_funding_pts, 2)
    bdown.total_score += bdown.funding_points

    # 3. GitHub Hits
    gh_pts = 0.0
    for hit in github_hits:
        kw = hit.get("keyword", "").lower()
        if kw in cfg.github.keyword_hits and not hit.get("is_false_positive", False):
            kw_cfg = cfg.github.keyword_hits[kw]
            hit_date = hit.get("date", now)
            days_old = (now - hit_date).total_seconds() / 86400.0
            mult = apply_decay(1.0, days_old, kw_cfg.decay_half_life_days)
            hit_pts = kw_cfg.points * mult
            gh_pts += hit_pts

            hash_short = hit.get("hash", "unknown")[:7]
            bdown.github_details[hash_short] = (
                f"Keyword '{kw}' ({hit_date.strftime('%Y-%m-%d')}). "
                f"Raw: {kw_cfg.points}. Decay: {round(mult, 2)}x."
            )
            bdown.decay_multipliers_applied[f"github_{hash_short}"] = round(mult, 3)

    bdown.github_points = round(min(gh_pts, cfg.github.max_category_points), 2)
    bdown.total_score = round(bdown.total_score + bdown.github_points, 2)

    return bdown
