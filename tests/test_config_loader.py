"""
Config loader tests — valid YAML loads, broken YAML rejected,
out-of-range co_lead_multiplier, watchlist >= immediate_alert,
invalid quiet hours, and hot-reload preserves old config on validation failure.
"""
import os
import tempfile

import pytest

import app.core.config_loader as config_loader
from app.core.config_loader import AppConfig, _CONFIG_LOCK, reload_config


VALID_YAML = """
vcs:
  tier_1: ["a16z", "Paradigm"]
  tier_2: ["Dragonfly"]

scoring:
  tvl:
    min_m: 5
    max_m: 50
    max_points: 20
    decay_half_life_days: null
  tvl_growth_30d:
    min_pct: 10
    max_pct: 100
    max_points: 15
  funding:
    max_category_points: 25
    tier_1_base_pts: 20
    tier_2_base_pts: 10
    co_lead_multiplier: 0.25
    decay_half_life_days: 180
  github:
    max_category_points: 30
    keyword_hits:
      tge:
        points: 25
        decay_half_life_days: 60

thresholds:
  immediate_alert: 75
  watchlist: 50
  alert_dedup_delta: 10

operational:
  timezone: Asia/Jakarta
  quiet_hours:
    - "23:00"
    - "07:00"
"""


def _write_temp_yaml(content: str) -> str:
    fd, path = tempfile.mkstemp(suffix=".yaml")
    with os.fdopen(fd, "w") as f:
        f.write(content)
    return path


class TestConfigLoader:
    def test_valid_yaml_loads(self):
        path = _write_temp_yaml(VALID_YAML)
        try:
            success, msg = reload_config(path)
            assert success is True
            assert msg == ""
        finally:
            os.unlink(path)

    def test_broken_yaml_rejected(self):
        path = _write_temp_yaml("{{{{not yaml at all")
        try:
            success, msg = reload_config(path)
            assert success is False
            assert len(msg) > 0
        finally:
            os.unlink(path)

    def test_co_lead_multiplier_out_of_range_rejected(self):
        bad = VALID_YAML.replace("co_lead_multiplier: 0.25", "co_lead_multiplier: 1.5")
        path = _write_temp_yaml(bad)
        try:
            success, msg = reload_config(path)
            assert success is False
            assert "co_lead_multiplier" in msg
        finally:
            os.unlink(path)

    def test_watchlist_gte_immediate_alert_rejected(self):
        bad = VALID_YAML.replace("watchlist: 50", "watchlist: 80")
        path = _write_temp_yaml(bad)
        try:
            success, msg = reload_config(path)
            assert success is False
            assert "watchlist" in msg
        finally:
            os.unlink(path)

    def test_invalid_quiet_hours_rejected(self):
        bad = VALID_YAML.replace('"23:00"', '"25:00"')
        path = _write_temp_yaml(bad)
        try:
            success, msg = reload_config(path)
            assert success is False
            assert "Time out of range" in msg or "Invalid" in msg
        finally:
            os.unlink(path)

    def test_single_quiet_hour_rejected(self):
        bad = VALID_YAML.replace(
            'quiet_hours:\n    - "23:00"\n    - "07:00"',
            'quiet_hours:\n    - "23:00"',
        )
        path = _write_temp_yaml(bad)
        try:
            success, msg = reload_config(path)
            assert success is False
            assert "two elements" in msg
        finally:
            os.unlink(path)

    def test_hot_reload_preserves_old_config_on_failure(self, mock_config):
        """Load valid config, then attempt broken reload — old config must survive."""
        # mock_config is already loaded via autouse fixture
        old_threshold = mock_config.thresholds.immediate_alert

        # Attempt to load garbage
        path = _write_temp_yaml("completely: broken: yaml: {{{")
        try:
            success, _ = reload_config(path)
            assert success is False
        finally:
            os.unlink(path)

        # Original config must still be intact
        with _CONFIG_LOCK:
            current = config_loader._ACTIVE_CONFIG
        assert current is not None
        assert current.thresholds.immediate_alert == old_threshold
