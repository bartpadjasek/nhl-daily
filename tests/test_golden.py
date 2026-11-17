"""Golden-file tests: the rendered emails must not change by accident.

The input is a saved data dict (tests/golden/digest_input.json, captured from a
real preview run on 15 Nov 2026) with fixed stub text for every generated
field, so rendering needs no network and no model. Variants cover the cards the
base input doesn't show (playoff race, playoff bracket) and the season recap.

To regenerate after an intended change:  UPDATE_GOLDEN=1 pytest tests/test_golden.py
Any change to a golden file is a behaviour change and must be reported.
"""

import copy
import json
import os

import pytest
from conftest import FIXTURES, load_fixture

import emailer
import nhl

GOLDEN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "golden")
UPDATE = os.environ.get("UPDATE_GOLDEN") == "1"


def _base() -> dict:
    with open(os.path.join(GOLDEN, "digest_input.json"), encoding="utf-8") as f:
        return json.load(f)


def _race_variant() -> dict:
    """Stretch-run regular season: playoff race card, analysis and magic number."""
    inp = _base()
    data = inp["data"]
    standings = load_fixture("standings_2026-11-15.json")["standings"]
    today_games = [
        {"awayTeam": {"abbrev": "VGK"}, "homeTeam": {"abbrev": "DAL"}},
        {"awayTeam": {"abbrev": "WPG"}, "homeTeam": {"abbrev": "STL"}},
    ]
    race = nhl._extract_playoff_race(standings, today_games)
    race["our_gp"] = 70
    race["our_games_remaining"] = 12
    data["playoff_race"] = race
    data["playoff_race_analysis"] = (
        "Edmonton holds the Pacific's top spot with room to spare.\n"
        "- VGK @ DAL: a Dallas win in regulation keeps Vegas four back."
    )
    data["magic_number"] = 12
    return inp


def _bracket_variant() -> dict:
    """Playoffs: bracket instead of standings, playoff scorers."""
    inp = _base()
    data = inp["data"]
    with open(os.path.join(FIXTURES, "playoff_bracket_2026.json"), encoding="utf-8") as f:
        data["playoff_bracket"] = nhl._extract_playoff_bracket(json.load(f))
    data["conference_standings"] = None
    data["playoff_race"] = None
    data["playoff_scorers"] = True
    return inp


def _recap_input() -> dict:
    data = _base()["data"]
    with open(os.path.join(FIXTURES, "playoff_bracket_2026.json"), encoding="utf-8") as f:
        bracket = nhl._extract_playoff_bracket(json.load(f))
    return {
        "overview": "Edmonton's season ended in the first round.\n\nIt was still a good year.",
        "good_bad_middling": {
            "good": "McDavid's scoring pace.",
            "bad": "The penalty kill.",
            "middling": "Goaltending depth.",
        },
        "player_grades": [
            {"name": "Connor McDavid", "position": "C", "grade": "A", "reasoning": "Led the team."},
            {"name": "Devon Levi", "position": "G", "grade": "B+", "reasoning": "Steady."},
        ],
        "offseason_priorities": [
            {
                "priority": "Re-sign the top pair",
                "label": "Critical",
                "detail": "Cap space is tight.",
            },
            {"priority": "Add a scoring winger", "label": "Important", "detail": "Depth scoring."},
        ],
        "last_game": copy.deepcopy(data["last_game"]),
        "top_scorers": copy.deepcopy(data["top_scorers"]),
        "standings": copy.deepcopy(data["standings"]),
        "playoff_bracket": bracket,
    }


def _render_digest(inp: dict) -> tuple[str, str]:
    return emailer.render_email(inp["subject"], inp["briefing"], inp["data"])


CASES = {
    "digest.html": lambda: _render_digest(_base())[0],
    "digest.txt": lambda: _render_digest(_base())[1],
    "digest_race.html": lambda: _render_digest(_race_variant())[0],
    "digest_bracket.html": lambda: _render_digest(_bracket_variant())[0],
    "digest_bracket.txt": lambda: _render_digest(_bracket_variant())[1],
    "recap.html": lambda: emailer.build_recap_html(_recap_input()),
}


@pytest.mark.parametrize("name", sorted(CASES))
def test_golden(name):
    rendered = CASES[name]()
    path = os.path.join(GOLDEN, name)
    if UPDATE:
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(rendered)
    with open(path, encoding="utf-8", newline="") as f:
        expected = f.read()
    assert rendered == expected, f"{name} differs from its golden file"
