"""
Thread-safe YAML config loader with Pydantic validation.
Uses int() parsing for quiet_hours to handle "9:00" natively without regex traps.
"""
import threading
from typing import Dict, List, Optional, Tuple

import yaml
from loguru import logger
from pydantic import BaseModel, field_validator, model_validator


class TvlConfig(BaseModel):
    min_m: float
    max_m: float
    max_points: float
    decay_half_life_days: Optional[int] = None


class TvlGrowthConfig(BaseModel):
    min_pct: float
    max_pct: float
    max_points: float


class FundingConfig(BaseModel):
    max_category_points: float
    tier_1_base_pts: float
    tier_2_base_pts: float
    co_lead_multiplier: float
    decay_half_life_days: int

    @model_validator(mode="after")
    def validate_multiplier(self) -> "FundingConfig":
        if not (0.0 <= self.co_lead_multiplier <= 1.0):
            raise ValueError("co_lead_multiplier must be between 0 and 1.0")
        return self


class KeywordConfig(BaseModel):
    points: float
    decay_half_life_days: int


class GithubConfig(BaseModel):
    max_category_points: float
    keyword_hits: Dict[str, KeywordConfig]


class ScoringConfig(BaseModel):
    tvl: TvlConfig
    tvl_growth_30d: TvlGrowthConfig
    funding: FundingConfig
    github: GithubConfig


class ThresholdsConfig(BaseModel):
    immediate_alert: float
    watchlist: float
    alert_dedup_delta: float

    @model_validator(mode="after")
    def validate_thresholds(self) -> "ThresholdsConfig":
        if self.watchlist >= self.immediate_alert:
            raise ValueError("watchlist must be strictly less than immediate_alert")
        return self


class OperationalConfig(BaseModel):
    timezone: str
    quiet_hours: List[str]

    @field_validator("quiet_hours")
    @classmethod
    def validate_quiet_hours(cls, v: List[str]) -> List[str]:
        if len(v) != 2:
            raise ValueError("quiet_hours must contain exactly two elements")
        for qh in v:
            parts = qh.split(":")
            if len(parts) != 2:
                raise ValueError(f"Invalid time format: {qh}. Expected HH:MM")
            try:
                h, m = int(parts[0]), int(parts[1])
                if not (0 <= h <= 23 and 0 <= m <= 59):
                    raise ValueError(f"Time out of range: {qh}")
            except ValueError:
                raise ValueError(f"Invalid time values in: {qh}")
        return v


class VcConfig(BaseModel):
    tier_1: List[str]
    tier_2: List[str]


class AppConfig(BaseModel):
    vcs: VcConfig
    scoring: ScoringConfig
    thresholds: ThresholdsConfig
    operational: OperationalConfig


_ACTIVE_CONFIG: Optional[AppConfig] = None
_CONFIG_LOCK = threading.Lock()


def reload_config(filepath: str = "config.yaml") -> Tuple[bool, str]:
    global _ACTIVE_CONFIG
    try:
        with open(filepath, "r") as f:
            raw_data = yaml.safe_load(f)

        # Validate BEFORE touching the live global state
        new_config = AppConfig(**raw_data)

        with _CONFIG_LOCK:
            _ACTIVE_CONFIG = new_config

        logger.success("Configuration successfully validated and reloaded.")
        return True, ""
    except Exception as e:
        logger.error(f"Failed to reload config: {str(e)}")
        return False, str(e)


def get_config() -> AppConfig:
    global _ACTIVE_CONFIG
    if _ACTIVE_CONFIG is None:
        success, msg = reload_config()
        if not success:
            raise RuntimeError(f"Fatal: Cannot load initial config: {msg}")
    with _CONFIG_LOCK:
        return _ACTIVE_CONFIG  # type: ignore[return-value]
