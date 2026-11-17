"""Outside text is escaped once, through emailer.theme.esc, everywhere it enters HTML."""

import copy
import json
import os

from conftest import ROOT

import emailer
from emailer.recap import build_recap_html
from emailer.theme import esc

NASTY = 'A <b>bold</b> & "quoted" claim'
SAFE = "A &lt;b&gt;bold&lt;/b&gt; &amp; &quot;quoted&quot; claim"


def test_esc():
    assert esc(NASTY) == SAFE
    assert esc("Edmonton's") == "Edmonton's"  # apostrophes unchanged


def _data() -> dict:
    with open(os.path.join(ROOT, "tests", "golden", "digest_input.json"), encoding="utf-8") as f:
        return json.load(f)


def test_every_outside_string_in_the_digest_is_escaped():
    inp = _data()
    d = inp["data"]
    lg = d["last_game"]
    lg["venue"] = NASTY
    lg["goalies"][0]["name"] = NASTY
    lg["opponent_goalie"]["name"] = NASTY
    lg["scoring_summary"][1]["goals"][0]["scorer"] = NASTY
    lg["scoring_summary"][1]["goals"][0]["assists"] = [NASTY]
    lg["three_stars"][0]["name"] = NASTY
    lg["three_stars"][0]["summary"] = NASTY
    d["next_game"]["venue"] = NASTY
    d["next_game_preview"]["last_meeting"]["location"] = NASTY
    d["next_game_preview"]["top_forward"]["name"] = NASTY
    d["road_weather"]["city"] = NASTY
    d["road_weather"]["description"] = NASTY
    d["top_scorers"][0]["name"] = NASTY
    d["player_of_week"]["name"] = NASTY
    d["milestones"][0]["name"] = NASTY
    d["injuries"][0]["player"] = NASTY
    d["injuries"][0]["position"] = NASTY
    d["prospects"][0]["name"] = NASTY
    d["prospects"][0]["team"] = NASTY
    d["conference_standings"]["Pacific"][1]["name"] = NASTY
    d["on_this_day"]["text"] = NASTY
    d["what_we_learned"] = [NASTY]
    d["fine_print"] = NASTY
    d["missing_data"] = [{"section": NASTY, "reason": NASTY}]
    html, _ = emailer.render_email(NASTY, NASTY, d)
    assert "<b>bold</b>" not in html
    assert '"quoted"' not in html
    assert html.count(SAFE) >= 25


def test_recap_text_is_escaped():
    data = {
        "overview": NASTY,
        "good_bad_middling": {"good": f"**{NASTY}** {NASTY}", "bad": NASTY, "middling": NASTY},
        "player_grades": [{"name": NASTY, "position": NASTY, "grade": NASTY, "reasoning": NASTY}],
        "offseason_priorities": [{"priority": NASTY, "label": NASTY, "detail": NASTY}],
        "last_game": {},
        "standings": {},
    }
    html = build_recap_html(copy.deepcopy(data))
    assert "<b>bold</b>" not in html
    assert html.count(SAFE) >= 10
