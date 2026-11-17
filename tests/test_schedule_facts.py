"""Previous/last meetings, season series words, trips and back-to-backs."""

from datetime import date

import digest
import nhl

REF = date(2026, 11, 15)
TOR_GAME_ID = 2026020314


def test_previous_meeting_with_team_just_played_excludes_reported_game(schedule_games):
    meeting = nhl._extract_last_meeting(schedule_games, "TOR", REF, exclude_game_id=TOR_GAME_ID)
    assert meeting["date"] == "2026-10-24"
    assert meeting["result"] == "L"
    assert (meeting["our_score"], meeting["opponent_score"]) == (2, 7)
    assert meeting["home_or_away"] == "home"
    assert meeting["location"] == "in Edmonton"
    text = digest._last_meeting_text(meeting, "TOR", "Previous meeting")
    assert text == (
        "Previous meeting with TOR: Saturday, October 24 (22 days ago), "
        "in Edmonton, lost 2-7 in regulation"
    )


def test_last_meeting_includes_reported_game_without_exclusion(schedule_games):
    meeting = nhl._extract_last_meeting(schedule_games, "TOR", REF)
    assert meeting["date"] == "2026-11-14"
    assert meeting["location"] == "in Toronto"


def test_last_meeting_with_next_opponent(schedule_games):
    meeting = nhl._extract_last_meeting(schedule_games, "PHI", REF)
    assert meeting["date"] == "2026-11-11"
    assert meeting["period_type"] == "OT"
    assert digest._last_meeting_text(meeting, "PHI") == (
        "Last meeting with PHI: Wednesday, November 11 (4 days ago), in Edmonton, "
        "won 3-2 in overtime"
    )


def test_season_series_in_words(schedule_games):
    ss = nhl._extract_season_series(schedule_games, "TOR")
    assert digest._series_words(ss) == "Oilers 1 win, 1 loss"
    assert digest._series_words({"wins": 2, "losses": 0, "ot_losses": 1}) == (
        "Oilers 2 wins, 0 losses, 1 overtime or shootout loss"
    )


def _notes(schedule_games):
    upcoming = nhl._extract_upcoming_games(schedule_games, n=6, ref_date=REF)
    return upcoming, nhl._extract_schedule_notes(upcoming, schedule_games)


def test_road_trip_position_counts_games_already_played(schedule_games):
    upcoming, notes = _notes(schedule_games)
    assert [g["opponent"] for g in notes["played"]] == ["TOR"]
    assert (notes["position"], notes["total"]) == (2, 6)
    assert notes["run_reaches_end"] is False
    assert digest._schedule_note_text(notes, upcoming[0]) == (
        "road trip, game 2 of 6 tonight (TOR played; then PHI Nov 15, FLA Nov 17, "
        "TBL Nov 19, CAR Nov 21, STL Nov 22)"
    )


def test_back_to_backs_next_game_and_later_pair(schedule_games):
    upcoming, notes = _notes(schedule_games)
    assert notes["next_is_back_to_back"] is True
    assert [[a["opponent"], b["opponent"]] for a, b in notes["back_to_backs"]] == [["CAR", "STL"]]
    assert digest._back_to_back_text(notes, upcoming[0]) == (
        "tonight at PHI is the second game in two nights; CAR and STL are also on consecutive days"
    )


def test_homestand_starting_without_back_to_back():
    games = [
        {
            "id": 1,
            "gameDate": "2026-11-01",
            "gameState": "OFF",
            "awayTeam": {"abbrev": "EDM", "score": 2},
            "homeTeam": {"abbrev": "VAN", "score": 1},
        },
        {
            "id": 2,
            "gameDate": "2026-11-04",
            "gameState": "FUT",
            "awayTeam": {"abbrev": "SEA"},
            "homeTeam": {"abbrev": "EDM"},
        },
        {
            "id": 3,
            "gameDate": "2026-11-06",
            "gameState": "FUT",
            "awayTeam": {"abbrev": "CGY"},
            "homeTeam": {"abbrev": "EDM"},
        },
        {
            "id": 4,
            "gameDate": "2026-11-08",
            "gameState": "FUT",
            "awayTeam": {"abbrev": "EDM"},
            "homeTeam": {"abbrev": "WPG"},
        },
    ]
    upcoming = nhl._extract_upcoming_games(games, n=6, ref_date=date(2026, 11, 2))
    notes = nhl._extract_schedule_notes(upcoming, games)
    assert notes["played"] == []
    assert (notes["position"], notes["total"]) == (1, 2)
    assert notes["next_is_back_to_back"] is False
    assert digest._back_to_back_text(notes, upcoming[0]) == ""
    assert digest._schedule_note_text(notes, upcoming[0]) == (
        "homestand, game 1 of 2 on Wednesday, November 4 (starts with SEA Nov 4, CGY Nov 6)"
    )


def test_division_gap_line():
    standings = [
        {
            "teamAbbrev": {"default": "EDM"},
            "divisionAbbrev": "P",
            "divisionSequence": 1,
            "points": 33,
            "gamesPlayed": 21,
        },
        {
            "teamAbbrev": {"default": "VGK"},
            "divisionAbbrev": "P",
            "divisionSequence": 2,
            "points": 29,
            "gamesPlayed": 21,
        },
    ]
    gap = nhl._extract_division_gap(standings)
    assert (
        nhl.division_gap_text(gap) == "Pacific: 1st, 4 points ahead of VGK with equal games played."
    )


def test_goalie_starts_merge_abbreviated_names_and_add_reported_game():
    import game_log

    log = [
        {
            "date": "2026-11-09",
            "opponent": "NYR",
            "result": "W",
            "our_score": 3,
            "opponent_score": 1,
            "home_or_away": "home",
            "goalie": {"name": "D. Levi", "saves": 28, "shots_against": 29},
        },
        {
            "date": "2026-11-11",
            "opponent": "PHI",
            "result": "W",
            "our_score": 3,
            "opponent_score": 2,
            "home_or_away": "home",
            "goalie": {"name": "T. Jarry", "saves": 30, "shots_against": 32},
        },
    ]
    last_game = {
        "date": "2026-11-14",
        "opponent": "TOR",
        "result": "W",
        "our_score": 1,
        "opponent_score": 0,
        "home_or_away": "away",
        "goalie": {"name": "Devon Levi", "saves": 19, "shots_against": 19},
    }
    starts = game_log.goalie_starts(log, last_game)
    assert [o["name"] for o in starts["order"]] == ["Devon Levi", "T. Jarry", "Devon Levi"]
    levi = starts["by_goalie"][0]
    assert levi["name"] == "Devon Levi"
    assert [s["date"] for s in levi["starts"]] == ["2026-11-14", "2026-11-09"]


def test_division_gap_from_saved_standings():
    from conftest import load_fixture

    gap = nhl._extract_division_gap(load_fixture("standings_2026-11-15.json")["standings"])
    assert nhl.division_gap_text(gap) == (
        "Pacific: 1st, 4 points ahead of VGK with equal games played."
    )
