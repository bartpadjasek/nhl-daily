"""Reference date and relative-day wording."""

from datetime import UTC, date, datetime

import digest
import nhl

GAME_NIGHT = date(2026, 11, 14)  # EDM 1-0 at TOR


class _FrozenDatetime(datetime):
    """datetime whose now() is 23:50 in Edmonton on game night.

    Built in LOCAL_TZ rather than from a fixed UTC offset: tz databases differ
    on Alberta's offset from November 2026 (UTC-7 vs permanent UTC-6).
    """

    @classmethod
    def now(cls, tz=None):
        moment = datetime(2026, 11, 14, 23, 50, tzinfo=nhl.LOCAL_TZ)
        return moment.astimezone(tz or UTC)


def test_run_at_2350_edmonton_on_game_night_reads_as_next_morning(monkeypatch):
    monkeypatch.setattr(nhl, "datetime", _FrozenDatetime)
    assert nhl.local_today() == GAME_NIGHT  # still the 14th in Edmonton
    ref = nhl.reference_date(GAME_NIGHT)
    assert ref == date(2026, 11, 15)

    when = nhl._last_game_when_where("2026-11-14", {}, {}, ref)
    assert when["days_ago"] == 1
    assert nhl.past_day_phrase(when["days_ago"], when["weekday"], when["date_label"]) == (
        "last night"
    )

    nxt = nhl._extract_next_game_info(
        {"gameDate": "2026-11-15", "awayTeam": {"abbrev": "EDM"}, "homeTeam": {"abbrev": "PHI"}},
        ref,
    )
    assert nxt["is_today"] is True
    assert digest._next_game_when(nxt) == "tonight, Sunday, November 15"


def test_reference_date_is_the_later_of_today_and_the_day_after_the_game():
    assert nhl.reference_date(GAME_NIGHT, today=date(2026, 11, 14)) == date(2026, 11, 15)
    assert nhl.reference_date(GAME_NIGHT, today=date(2026, 11, 15)) == date(2026, 11, 15)
    assert nhl.reference_date(GAME_NIGHT, today=date(2026, 11, 17)) == date(2026, 11, 17)
    assert nhl.reference_date(None, today=date(2026, 11, 17)) == date(2026, 11, 17)


def test_past_day_phrases():
    assert nhl.past_day_phrase(0, "Saturday", "November 14") == "earlier today"
    assert nhl.past_day_phrase(1, "Saturday", "November 14") == "last night"
    assert nhl.past_day_phrase(3, "Saturday", "November 14") == (
        "on Saturday, November 14 (3 days ago)"
    )
    assert nhl.past_day_phrase(None, "Saturday", "November 14") == "on Saturday, November 14"


def test_next_game_phrases():
    base = {"date": "2026-11-17"}
    assert digest._next_game_when({**base, "days_until": 0}) == "tonight, Tuesday, November 17"
    assert digest._next_game_when({**base, "days_until": 1}) == "tomorrow, Tuesday, November 17"
    assert digest._next_game_when({**base, "days_until": 2}) == ("Tuesday, November 17 (in 2 days)")


def test_forced_send_days_later_uses_weekday():
    ref = nhl.reference_date(GAME_NIGHT, today=date(2026, 11, 17))
    when = nhl._last_game_when_where("2026-11-14", {}, {}, ref)
    assert digest._last_game_when(when) == "on Saturday, November 14 (3 days ago)"


def test_key_facts_today_line_uses_reference_date():
    lines = digest._key_facts_lines({"reference_date": "2026-11-15"})
    assert lines[0] == "Today: Sunday, November 15, 2026"
