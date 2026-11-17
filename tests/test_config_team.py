"""config.toml loading, the team table, and the standings logic for other teams."""

import pytest
from conftest import load_fixture

import config
import nhl
from team import TEAMS, get_team


def _write(tmp_path, text: str) -> str:
    path = tmp_path / "config.toml"
    path.write_text(text, encoding="utf-8")
    return str(path)


def test_team_table_has_all_32_teams_in_four_divisions():
    assert len(TEAMS) == 32
    divisions = {}
    for t in TEAMS.values():
        divisions.setdefault((t.conference, t.division), []).append(t.abbrev)
    assert {k: len(v) for k, v in divisions.items()} == {
        ("W", "P"): 8,
        ("W", "C"): 8,
        ("E", "A"): 8,
        ("E", "M"): 8,
    }


def test_defaults_follow_the_team(tmp_path):
    s = config.load_settings(_write(tmp_path, '[team]\nabbrev = "tor"\n'))
    assert s.team.name == "Toronto Maple Leafs"
    assert str(s.local_tz) == "America/Toronto" and str(s.display_tz) == "America/Toronto"
    assert s.newsletter_name == "Maple Leafs Daily"
    assert (s.llm.provider, s.llm.model, s.llm.api_key_env) == (
        "anthropic",
        config.DEFAULT_MODELS["anthropic"],
        "ANTHROPIC_API_KEY",
    )


def test_display_timezone_can_differ(tmp_path):
    s = config.load_settings(
        _write(tmp_path, '[team]\nabbrev = "EDM"\n[time]\ndisplay_timezone = "Europe/Stockholm"\n')
    )
    assert str(s.local_tz) == "America/Edmonton" and str(s.display_tz) == "Europe/Stockholm"


@pytest.mark.parametrize(
    "text, message",
    [
        ('[team]\nabbrev = "XXX"\n', "Unknown team"),
        ('[team]\nabbrev = "EDM"\n[time]\nlocal_timezone = "Mars/Base"\n', "IANA"),
        ('[team]\nabbrev = "EDM"\n[llm]\nprovider = "cohere"\n', "provider"),
        ('[team]\nabbrev = "EDM"\n[llm]\nprovider = "openai_compatible"\n', "base_url"),
        ('[team]\nabbrev = "EDM"\n[email]\nhide_cards = ["reddit"]\n', "hide_cards"),
    ],
)
def test_invalid_settings_name_the_setting(tmp_path, text, message):
    with pytest.raises(config.ConfigError, match=message):
        config.load_settings(_write(tmp_path, text))


def test_openai_compatible_settings(tmp_path):
    s = config.load_settings(
        _write(
            tmp_path,
            '[team]\nabbrev = "SEA"\n[llm]\nprovider = "openai_compatible"\n'
            'model = "llama3.1"\nbase_url = "http://localhost:11434/v1"\n',
        )
    )
    assert (s.llm.model, s.llm.base_url, s.llm.api_key_env) == (
        "llama3.1",
        "http://localhost:11434/v1",
        "LLM_API_KEY",
    )


def test_eastern_team_gets_its_own_conference_and_division(monkeypatch):
    standings = load_fixture("standings_2026-11-15.json")["standings"]
    monkeypatch.setattr(nhl, "TEAM_ABBREV", "TOR")
    conf, divs = nhl.our_conference(standings)
    assert conf == "E" and divs[0] == "A" and set(divs) == {"A", "M"}

    table = nhl._extract_conference_standings(standings)
    assert list(table) == ["Atlantic", "Metropolitan"]
    assert sum(len(v) for v in table.values()) == 16
    assert any(t["is_us"] and t["abbrev"] == "TOR" for t in table["Atlantic"])

    race = nhl._extract_playoff_race(standings, [])
    teams = {t["abbrev"] for t in race["bubble_teams"]}
    assert teams and all(get_team(a).conference == "E" for a in teams)

    gap = nhl._extract_division_gap(standings)
    assert gap["division"] == "Atlantic"


def test_hidden_cards_are_left_out(monkeypatch):
    import dataclasses
    import json
    import os

    import emailer
    from emailer import digest_html

    with open(
        os.path.join(os.path.dirname(__file__), "golden", "digest_input.json"), encoding="utf-8"
    ) as f:
        inp = json.load(f)
    full, _ = emailer.render_email(inp["subject"], inp["briefing"], inp["data"])
    assert "Season 5v5" in full and "Prospects" in full
    hidden = dataclasses.replace(config.SETTINGS, hide_cards=frozenset({"season_5v5", "prospects"}))
    monkeypatch.setattr(digest_html, "SETTINGS", hidden)
    less, _ = emailer.render_email(inp["subject"], inp["briefing"], inp["data"])
    assert "Season 5v5" not in less and "Prospects" not in less and "Three Stars" in less
