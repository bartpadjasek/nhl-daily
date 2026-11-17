"""run_pipeline end to end with every fetch and model call stubbed.

Regression: on 16 Nov 2026 a scheduled --now run took the preview path because
a local variable named `preview` (the next-game preview dict) overwrote the
run_pipeline(preview=...) flag. A real run must send and log the game; a
preview run must do neither.
"""

import copy
import json
import os

import pytest
from conftest import ROOT

import scheduler


@pytest.fixture
def pipeline(monkeypatch, tmp_path):
    with open(os.path.join(ROOT, "tests", "golden", "digest_input.json"), encoding="utf-8") as f:
        golden = json.load(f)
    calls = {"sent": [], "logged": []}

    stubs = {
        "load_game_log": lambda: [],
        "_has_unsent_game": lambda log: True,
        "get_team_data": lambda: copy.deepcopy(golden["data"]),
        "fetch_team_headlines": lambda: [],
        "fetch_team_injuries": lambda: [],
        "fetch_team_advanced_stats": lambda: {"corsi_pct": 50.0, "fenwick_pct": 50.0, "pdo": 100.0},
        "fetch_game_weather": lambda *a: None,
        "fetch_opponent_goalie_news": lambda name: [],
        "find_likely_starter": lambda goalies, headlines: None,
        "get_prospects_data": lambda: [],
        "get_player_career_context": lambda club: {},
        "fetch_club_stats": lambda: {},
        "generate_digest": lambda data: "Briefing.",
        "generate_what_we_learned": lambda data, briefing: [],
        "generate_on_this_day": lambda ref: None,
        "generate_playoff_race_analysis": lambda data: "",
        "generate_fine_print": lambda data: "Fine print",
        "generate_subject": lambda data: "Subject",
        "enable_preview": lambda path: None,
        "send_email": lambda subject, briefing, data: calls["sent"].append(subject),
        "append_game": lambda game, games=None: calls["logged"].append(game["date"]),
    }
    for name, fn in stubs.items():
        monkeypatch.setattr(scheduler, name, fn)
    monkeypatch.setattr(scheduler, "PREVIEW_DIR", str(tmp_path / "preview"))
    assert golden["data"]["next_game_preview"], "fixture must have a next-game preview"
    return calls, tmp_path


def test_real_run_sends_and_logs_even_with_a_next_game_preview(pipeline):
    calls, tmp_path = pipeline
    assert scheduler.run_pipeline() is True
    assert calls["sent"] == ["Subject"]
    assert calls["logged"] == ["2026-11-14"]
    assert not (tmp_path / "preview").exists()


def test_preview_run_writes_files_and_never_sends(pipeline):
    calls, tmp_path = pipeline
    assert scheduler.run_pipeline(preview=True) is True
    assert calls["sent"] == [] and calls["logged"] == []
    assert (tmp_path / "preview" / "digest.html").exists()
