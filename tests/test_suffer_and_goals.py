"""Suffer-O-Meter cases from real games, and goal-timing words."""

import pytest
from conftest import load_fixture

import nhl
from scheduler import _calculate_suffer_score


def _game(game_id: str, schedule_games: list[dict]) -> tuple[dict, dict]:
    """last_game + recent_form as get_team_data builds them, for a past game."""
    raw = next(g for g in schedule_games if str(g["id"]) == game_id)
    away_is_us = raw["awayTeam"]["abbrev"] == "EDM"
    edm, opp = (
        (raw["awayTeam"], raw["homeTeam"]) if away_is_us else (raw["homeTeam"], raw["awayTeam"])
    )
    period_type = nhl._game_period_type(raw)
    won = edm["score"] > opp["score"]
    last_game = {
        "result": "W" if won else ("OTL" if period_type in ("OT", "SO") else "L"),
        "our_score": edm["score"],
        "opponent_score": opp["score"],
        "period_type": period_type,
        "scoring_summary": nhl._extract_scoring_summary(load_fixture(f"landing_{game_id}.json")),
    }
    up_to = [g for g in schedule_games if g["gameDate"] <= raw["gameDate"]]
    return last_game, nhl._extract_recent_form(up_to, n=10)


def test_shutout_on_the_road_scores_1(schedule_games):
    last_game, form = _game("2026020314", schedule_games)  # 14 Nov at TOR, 1-0
    s = _calculate_suffer_score(last_game, form)
    assert s["score"] == 1
    assert s["reasons"] == ["one-goal win", "shutout", "4 straight wins"]


def test_overtime_win_after_blowing_two_goal_lead_scores_5(schedule_games):
    last_game, form = _game("2026020295", schedule_games)  # 11 Nov vs PHI, 3-2 OT
    s = _calculate_suffer_score(last_game, form)
    assert s["score"] == 5
    assert s["label"] == "A win, but it hurt. It always hurts."


def test_blowout_loss_scores_9(schedule_games):
    last_game, form = _game("2026020176", schedule_games)  # 24 Oct vs TOR, 2-7
    assert _calculate_suffer_score(last_game, form)["score"] == 9


def test_overtime_loss_label_is_for_losses():
    s = _calculate_suffer_score(
        {"result": "OTL", "our_score": 3, "opponent_score": 4, "period_type": "OT"}
    )
    assert s["score"] == 6
    assert s["label"] == "A point is a point. Allegedly."


@pytest.mark.parametrize(
    "clock, words",
    [
        ("06:59", "early in the 2nd"),
        ("07:00", "midway through the 2nd"),
        ("12:59", "midway through the 2nd"),
        ("13:00", "late in the 2nd"),
    ],
)
def test_goal_timing_words(clock, words):
    assert nhl.goal_phase(clock, "2nd") == words


def test_no_timing_words_in_overtime():
    assert nhl.goal_phase("03:10", "OT", "OT") == ""


def test_scoring_summary_carries_timing_words():
    summary = nhl._extract_scoring_summary(load_fixture("landing_2026020314.json"))
    goal = next(g for period in summary for g in period["goals"])
    assert (goal["time"], goal["phase"]) == ("15:34", "late in the 2nd")
