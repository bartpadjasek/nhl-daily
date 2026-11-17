"""Missing-data report for one pipeline run.

Every place that catches an error and drops a section calls `record()`. The
scheduler copies `entries()` onto the data dict as "missing_data", logs it as
one warning, and the email footer lists the dropped sections.
"""

_entries: list[dict] = []

NHL_UNAVAILABLE = "NHL data unavailable"


def reset() -> None:
    """Start a new run with an empty report."""
    _entries.clear()


def record(section: str, reason: str) -> None:
    """Note that `section` was left out of today's email because of `reason`."""
    if not any(e["section"] == section and e["reason"] == reason for e in _entries):
        _entries.append({"section": section, "reason": reason})


def entries() -> list[dict]:
    """A copy of everything recorded so far, in the order it happened."""
    return [dict(e) for e in _entries]


def footer_line(missing: list[dict]) -> str:
    """'Not included today: Top Scorers, Players to watch (NHL data unavailable).'

    Sections are grouped by reason, in the order they were first recorded.
    Returns "" when nothing is missing.
    """
    if not missing:
        return ""
    groups: dict[str, list[str]] = {}
    for e in missing:
        groups.setdefault(e["reason"], [])
        if e["section"] not in groups[e["reason"]]:
            groups[e["reason"]].append(e["section"])
    parts = [f"{', '.join(sections)} ({reason})" for reason, sections in groups.items()]
    return "Not included today: " + "; ".join(parts) + "."
