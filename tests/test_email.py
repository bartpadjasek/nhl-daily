"""Preheader length, _finalize_html idempotence, shutout card, goalie stars."""

from conftest import load_fixture

import emailer
import nhl

LONG_DATA = {
    "last_game": {
        "result": "W",
        "our_score": 7,
        "opponent_score": 6,
        "scoring_summary": [
            {
                "period_label": "1st",
                "goals": [
                    {"team": "EDM", "scorer": "Ryan Nugent-Hopkins", "assists": ["Connor McDavid"]},
                    {"team": "EDM", "scorer": "Ryan Nugent-Hopkins", "assists": ["Leon Draisaitl"]},
                    {"team": "EDM", "scorer": "Evan Bouchard", "assists": ["Ryan Nugent-Hopkins"]},
                ],
            }
        ],
        "goalie": {"name": "Tristan Jarry", "saves": 41, "shots_against": 47},
    },
    "next_game": {
        "opponent": "CBJ",
        "home_or_away": "away",
        "is_today": True,
        "time": "Wed 18 Nov, 01:00 CET",
    },
}


def test_preheader_stays_within_limit():
    pre = emailer._get_preheader(LONG_DATA)
    assert 0 < len(pre) <= emailer.PREHEADER_MAX


def test_finalize_html_is_idempotent():
    data = {
        "last_game": {
            "result": "W",
            "our_score": 1,
            "opponent_score": 0,
            "opponent": "TOR",
            "goalies": [{"name": "Devon Levi", "saves": 19, "shots_against": 19, "decision": "W"}],
            "opponent_goalie": {"name": "Anthony Stolarz", "saves": 22, "shots_against": 23},
        },
        "missing_data": [{"section": "Top Scorers", "reason": "NHL data unavailable"}],
    }
    once = emailer._finalize_html(emailer.build_html("Briefing.", data, "Sunday, November 15"))
    assert emailer._finalize_html(once) == once
    assert "Shutout" in once
    assert "19 saves, shutout" in once and "22 of 23" in once
    assert "Not included today: Top Scorers (NHL data unavailable)." in once


def test_goalie_stars_show_saves_not_gaa():
    box = load_fixture("boxscore_2026020314.json")
    landing = load_fixture("landing_2026020314.json")
    sched = next(
        g for g in load_fixture("edm_schedule_oct_nov_2026.json")["games"] if g["id"] == 2026020314
    )
    last_game = nhl._extract_last_game_info(sched, box)
    stars = nhl._extract_three_stars(landing)
    nhl._apply_goalie_star_lines(stars, last_game)
    assert [s["summary"] for s in stars if s["position"] == "G"] == [
        "22 of 23",
        "19 saves, shutout",
    ]
    assert last_game["shutout"]["saves"] == 19


def test_five_v_five_reading():
    assert emailer.five_v_five_reading(47.3, 103.6) == (
        "Being outshot at 5v5, with percentages running hot."
    )
    assert (
        emailer.five_v_five_reading(52, 100)
        == "Controlling play at 5v5, with percentages about normal."
    )
    assert (
        emailer.five_v_five_reading(50, 97.9)
        == "Roughly even at 5v5, with percentages running cold."
    )
