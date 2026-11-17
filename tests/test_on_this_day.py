"""On This Day: whole-word matching and the SKIP answer."""

from datetime import date
from types import SimpleNamespace

import digest

STEAMBOAT = (
    "The steamboat Louisiana's boilers exploded at the Gravier Street wharf in New Orleans, "
    "killing more than 150 people."
)
HOUSTON = "The Houston Oilers defeat the San Diego Chargers in the first AFL Championship Game."
EDMONTON = "The Edmonton Oilers win their first Stanley Cup, defeating the New York Islanders."


def test_steamboat_boilers_rejected():
    assert digest.is_team_event(STEAMBOAT) is False


def test_houston_oilers_rejected():
    assert digest.is_team_event(HOUSTON) is False


def test_edmonton_oilers_accepted():
    assert digest.is_team_event(EDMONTON) is True


def test_bare_oilers_needs_hockey_context():
    assert digest.is_team_event("The Oilers trade for a goaltender ahead of the NHL deadline.")
    assert not digest.is_team_event("The Oilers relocate to Tennessee.")


def test_listed_person_accepted_on_word_boundary():
    assert digest.is_team_event("Wayne Gretzky scores his 802nd goal.")
    assert not digest.is_team_event("Wayne Gretzkyville is founded.")


def _wiki_response(text):
    payload = {"events": [{"year": 1984, "text": text}]}
    return SimpleNamespace(status_code=200, json=lambda: payload)


def test_model_skip_hides_card(monkeypatch):
    monkeypatch.setattr(digest.requests, "get", lambda *a, **k: _wiki_response(EDMONTON))

    class _Client:
        messages = SimpleNamespace(
            create=lambda **k: SimpleNamespace(content=[SimpleNamespace(text="SKIP")])
        )

    monkeypatch.setattr(digest, "_get_client", lambda: _Client())
    assert digest.generate_on_this_day(date(2026, 5, 19)) is None


def test_no_matching_event_hides_card_without_model_call(monkeypatch):
    monkeypatch.setattr(digest.requests, "get", lambda *a, **k: _wiki_response(STEAMBOAT))

    def _fail(**k):
        raise AssertionError("model must not be called")

    monkeypatch.setattr(
        digest, "_get_client", lambda: SimpleNamespace(messages=SimpleNamespace(create=_fail))
    )
    assert digest.generate_on_this_day(date(2026, 11, 15)) is None
