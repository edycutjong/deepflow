"""
Pytest fixtures — full production VC lists and multiple keywords for category cap tests.
Includes testcontainers Postgres for integration tests.
"""
import pytest

import app.core.config_loader as config_loader
from app.core.config_loader import AppConfig, _CONFIG_LOCK
from testcontainers.postgres import PostgresContainer


@pytest.fixture(scope="session")
def postgres():
    with PostgresContainer("postgres:16-alpine") as pg:
        yield pg.get_connection_url()


@pytest.fixture(autouse=True)
def mock_config():
    """Overrides the global configuration state with full production mock data."""
    cfg = AppConfig(
        vcs={
            "tier_1": [
                "a16z",
                "Paradigm",
                "Polychain",
                "Multicoin",
                "Binance Labs",
                "Framework",
                "Variant",
                "Hack VC",
                "Placeholder",
            ],
            "tier_2": [
                "Dragonfly",
                "Coinbase Ventures",
                "Spartan Group",
                "Animoca",
                "Delphi Digital",
            ],
        },
        scoring={
            "tvl": {
                "min_m": 5,
                "max_m": 50,
                "max_points": 20,
                "decay_half_life_days": None,
            },
            "tvl_growth_30d": {"min_pct": 10, "max_pct": 100, "max_points": 15},
            "funding": {
                "max_category_points": 25,
                "tier_1_base_pts": 20,
                "tier_2_base_pts": 10,
                "co_lead_multiplier": 0.25,
                "decay_half_life_days": 180,
            },
            "github": {
                "max_category_points": 30,
                "keyword_hits": {
                    "tge": {"points": 25, "decay_half_life_days": 60},
                    "airdrop": {"points": 15, "decay_half_life_days": 90},
                },
            },
        },
        thresholds={
            "immediate_alert": 75,
            "watchlist": 50,
            "alert_dedup_delta": 10,
        },
        operational={
            "timezone": "Asia/Jakarta",
            "quiet_hours": ["23:00", "07:00"],
        },
    )

    with _CONFIG_LOCK:
        config_loader._ACTIVE_CONFIG = cfg

    yield cfg
