"""Shared test setup: repo root on sys.path, JSON fixtures, no network."""

import json
import os
import sys

# Pin the config before any project module is imported (config loads at import).
os.environ["NHL_DAILY_CONFIG"] = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "config_test.toml"
)

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
FIXTURES = os.path.join(ROOT, "tests", "fixtures")


def load_fixture(name: str) -> dict:
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    """Fresh NHL cache and run report per test; any real HTTP call fails loudly."""
    import nhl
    import run_report

    nhl.clear_cache()
    run_report.reset()
    monkeypatch.setattr(nhl, "_sleep", lambda s: None)

    def _no_network(*args, **kwargs):
        raise AssertionError("tests must not touch the network")

    monkeypatch.setattr(nhl._session, "get", _no_network)
    monkeypatch.setattr("requests.get", _no_network)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)


@pytest.fixture
def schedule_games() -> list[dict]:
    return load_fixture("edm_schedule_oct_nov_2026.json")["games"]
