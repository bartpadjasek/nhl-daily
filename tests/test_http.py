"""nhl._get retries 429s, honours Retry-After and caches by URL."""

import pytest
import requests

import nhl


def _response(status: int, body: bytes = b"{}", headers: dict | None = None):
    r = requests.Response()
    r.status_code = status
    r._content = body
    r.url = "https://api-web.nhle.com/v1/test"
    r.headers.update(headers or {})
    return r


def _install(monkeypatch, responses: list):
    calls = []
    sleeps = []

    def fake_get(url, **kwargs):
        calls.append(url)
        return responses.pop(0)

    monkeypatch.setattr(nhl._session, "get", fake_get)
    monkeypatch.setattr(nhl, "_sleep", sleeps.append)
    return calls, sleeps


def test_retries_429_then_succeeds(monkeypatch):
    calls, sleeps = _install(
        monkeypatch, [_response(429), _response(429), _response(200, b'{"ok": true}')]
    )
    assert nhl._get("https://api-web.nhle.com/v1/a") == {"ok": True}
    assert len(calls) == 3
    assert [s for s in sleeps if s >= 1] == [1, 2]


def test_honours_retry_after(monkeypatch):
    _, sleeps = _install(
        monkeypatch, [_response(429, headers={"Retry-After": "3"}), _response(200, b"{}")]
    )
    nhl._get("https://api-web.nhle.com/v1/b")
    assert 3.0 in sleeps


def test_gives_up_after_four_retries(monkeypatch):
    calls, _ = _install(monkeypatch, [_response(503) for _ in range(5)])
    with pytest.raises(RuntimeError):
        nhl._get("https://api-web.nhle.com/v1/c")
    assert len(calls) == 5


def test_does_not_retry_404(monkeypatch):
    calls, _ = _install(monkeypatch, [_response(404)])
    with pytest.raises(RuntimeError):
        nhl._get("https://api-web.nhle.com/v1/d")
    assert len(calls) == 1


def test_caches_successful_responses(monkeypatch):
    calls, _ = _install(monkeypatch, [_response(200, b'{"n": 1}')])
    assert nhl._get("https://api-web.nhle.com/v1/e") == {"n": 1}
    assert nhl._get("https://api-web.nhle.com/v1/e") == {"n": 1}
    assert len(calls) == 1


def test_point_streak_from_game_log():
    from conftest import load_fixture

    games, from_start = nhl._point_streak(load_fixture("game_log_mcdavid.json")["gameLog"])
    assert (games, from_start) == (21, True)
    assert nhl._point_streak([{"points": 1}, {"points": 0}, {"points": 2}]) == (1, False)
