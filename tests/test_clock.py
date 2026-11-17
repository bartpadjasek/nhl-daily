"""One clock: content time comes from nhl.local_now() (or the run's reference date).

Scans the source for datetime.now(), date.today() and .utcnow() calls and
fails on any call outside the functions listed here. Add a new entry only for
log timestamps, never for anything a reader sees or that selects data.
"""

import ast
import glob
import os

from conftest import ROOT

ALLOWED = {
    # The one shared content clock
    ("nhl.py", "local_now"),
    # Log timestamps only
    ("scheduler.py", "_log_timestamp"),
    ("scheduler.py", "_safe_run"),
    # Off limits for the cleanup brief (send gate, recap timing, MoneyPuck
    # season id); they still read the clock directly
    ("nhl.py", "latest_completed_game"),
    ("season_recap.py", "_has_upcoming_games"),
    ("season_recap.py", "_mark_recap_sent"),
    ("season_recap.py", "should_send_recap"),
    ("moneypuck.py", "_current_season_id"),
}
CLOCK_ATTRS = {"now", "today", "utcnow"}
CLOCK_OWNERS = {"datetime", "date"}


def _clock_calls(path: str):
    tree = ast.parse(open(path, encoding="utf-8").read())

    def visit(node, func):
        for child in ast.iter_child_nodes(node):
            name = func
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                name = child.name
            if (
                isinstance(child, ast.Call)
                and isinstance(child.func, ast.Attribute)
                and child.func.attr in CLOCK_ATTRS
            ):
                owner = child.func.value
                owner_name = (
                    owner.attr if isinstance(owner, ast.Attribute) else getattr(owner, "id", "")
                )
                if owner_name in CLOCK_OWNERS:
                    yield name, child.lineno
            yield from visit(child, name)

    yield from visit(tree, "<module>")


def test_no_new_content_clock_calls():
    found = []
    files = glob.glob(os.path.join(ROOT, "*.py")) + glob.glob(os.path.join(ROOT, "emailer", "*.py"))
    for path in files:
        rel = os.path.relpath(path, ROOT)
        for func, line in _clock_calls(path):
            if (os.path.basename(rel), func) not in ALLOWED:
                found.append(f"{rel}:{line} in {func}()")
    assert not found, "Use nhl.local_now() or the reference date instead of: " + ", ".join(found)


def test_allowlist_has_no_stale_entries():
    seen = set()
    for path in glob.glob(os.path.join(ROOT, "*.py")):
        for func, _ in _clock_calls(path):
            seen.add((os.path.basename(path), func))
    assert ALLOWED <= seen, f"remove stale entries: {sorted(ALLOWED - seen)}"


def test_tonights_games_follow_the_reference_date(monkeypatch):
    from datetime import date

    import nhl

    week = {
        "gameWeek": [
            {"date": "2026-11-14", "games": [{"id": 1}]},
            {"date": "2026-11-15", "games": [{"id": 2}]},
        ]
    }
    monkeypatch.setattr(nhl, "_get", lambda url: week)
    assert nhl.fetch_today_schedule(date(2026, 11, 15)) == [{"id": 2}]
