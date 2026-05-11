"""
Scoring tests — parametric gradient/decay, deterministic VC sorting,
and multi-keyword category capping.
"""
from datetime import datetime, timedelta, timezone

import pytest

from app.core.scoring import apply_decay, apply_gradient, generate_score


@pytest.mark.parametrize(
    "value, min_v, max_v, max_pts, expected",
    [
        (4.0, 5.0, 50.0, 20.0, 0.0),  # Below min
        (5.0, 5.0, 50.0, 20.0, 0.0),  # At min
        (27.5, 5.0, 50.0, 20.0, 10.0),  # Exact midpoint
        (50.0, 5.0, 50.0, 20.0, 20.0),  # At max
        (100.0, 5.0, 50.0, 20.0, 20.0),  # Above max
    ],
)
def test_apply_gradient(value, min_v, max_v, max_pts, expected):
    assert apply_gradient(value, min_v, max_v, max_pts) == expected


@pytest.mark.parametrize(
    "days_old, half_life, expected_multiplier",
    [
        (0, 180, 1.0),  # Brand new
        (180, 180, 0.5),  # Exactly 1 half-life
        (360, 180, 0.25),  # 2 half-lives
        (-10, 180, 1.0),  # Negative days (clock skew safeguard)
        (10, None, 1.0),  # No decay configured
    ],
)
def test_apply_decay(days_old, half_life, expected_multiplier):
    assert apply_decay(1.0, days_old, half_life) == expected_multiplier


def test_deterministic_vc_sorting_and_decay(mock_config):
    now = datetime.now(timezone.utc)
    round_date = now - timedelta(days=180)

    vcs = [
        {"name": "Dragonfly"},  # Tier 2 (10)
        {"name": "a16z"},  # Tier 1 (20)
        {"name": "Paradigm"},  # Tier 1 (20)
    ]

    bdown = generate_score(0, 0, vcs, round_date, [], now)

    # Sorting: a16z (20), Paradigm (20*0.25=5), Dragonfly (10*0.25=2.5) -> 27.5
    # Capped at 25.0
    # Decay applied (180 days = 0.5 multiplier) -> 12.5
    assert bdown.funding_points == 12.5
    assert "a16z, Paradigm, Dragonfly" in bdown.funding_details
    assert bdown.decay_multipliers_applied["funding"] == 0.5


def test_multiple_keyword_category_capping(mock_config):
    """TGE (25) + Airdrop (15) = 40. Should be strictly capped at 30 per config."""
    now = datetime.now(timezone.utc)

    github_hits = [
        {
            "keyword": "tge",
            "date": now,
            "hash": "abc1234",
            "is_false_positive": False,
        },
        {
            "keyword": "airdrop",
            "date": now,
            "hash": "def5678",
            "is_false_positive": False,
        },
    ]

    bdown = generate_score(0, 0, [], None, github_hits, now)

    assert bdown.github_points == 30.0  # Strictly capped
    assert "abc1234" in bdown.github_details
    assert "def5678" in bdown.github_details
