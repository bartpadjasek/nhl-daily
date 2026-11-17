"""Rolling game log for the NHL Daily digest.

Persists a JSON file in the repo with the last MAX_GAMES completed game
summaries. Loaded at the start of each pipeline run and passed to the model
as historical context, giving it season-long memory.
"""

import json
import logging
import os

from config import TEAM

logger = logging.getLogger(__name__)

GAME_LOG_PATH = os.path.join(os.path.dirname(__file__), "game_log.json")
MAX_GAMES = 20


def load_game_log() -> list[dict]:
    """Load the persisted game log from disk.

    Returns:
        List of game summary dicts, oldest first. Empty list if file is
        missing, empty, or unparseable.
    """
    try:
        with open(GAME_LOG_PATH, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
        return []
    except (FileNotFoundError, json.JSONDecodeError, OSError) as e:
        logger.warning("Could not load game log: %s", e)
        return []


def _derive_notes(last_game: dict) -> list[str]:
    """Derive descriptive notes from a last_game dict.

    Args:
        last_game: The last_game dict from nhl.get_team_data().

    Returns:
        List of short note strings, e.g. ["shutout", "overtime"].
    """
    notes = []
    result = last_game.get("result", "")
    our_score = last_game.get("our_score", 0)
    opp_score = last_game.get("opponent_score", 0)
    margin = abs(our_score - opp_score)
    # Entries written before period_type was stored won't have it
    period_type = (last_game.get("period_type") or "REG").upper()

    if result == "OTL":
        notes.append("overtime loss")
    elif result == "W" and period_type == "OT":
        notes.append("overtime win")
    elif result == "W" and period_type == "SO":
        notes.append("shootout win")
    elif result == "W" and margin >= 3:
        notes.append("comfortable win")
    elif result == "W" and margin == 1:
        notes.append("tight win")
    elif result == "L" and margin >= 3:
        notes.append("blowout loss")

    goalie = last_game.get("goalie")
    if goalie and goalie.get("shots_against", 0) > 0:
        if goalie.get("saves") == goalie.get("shots_against"):
            notes.append("shutout")

    # Comeback: check if opponent led but we won (approximation — if scoring
    # summary exists, check if opponent scored first)
    scoring = last_game.get("scoring_summary", [])
    if result == "W" and scoring:
        first_goal = next((g for period in scoring for g in period.get("goals", [])), None)
        if first_goal and first_goal.get("team") != TEAM.abbrev:
            notes.append("comeback win")

    return notes


def append_game(last_game: dict, games: list[dict] | None = None) -> None:
    """Append a completed game to the log and persist to disk.

    Builds a compact summary from last_game, appends it, trims to MAX_GAMES,
    then writes back to GAME_LOG_PATH. Logs a warning and returns on any error.

    Args:
        last_game: The last_game dict from nhl.get_team_data().
        games: Already-loaded game log list. If None, loads from disk.
    """
    if not last_game:
        return

    # Build compact summary
    top_skaters = [
        {"name": s["name"], "goals": s["goals"], "assists": s["assists"]}
        for s in last_game.get("top_skaters", [])[:3]
    ]

    goalie = None
    g = last_game.get("goalie")
    if g:
        goalie = {
            "name": g.get("name", ""),
            "saves": g.get("saves", 0),
            "shots_against": g.get("shots_against", 0),
        }

    entry = {
        "date": last_game.get("date", ""),
        "opponent": last_game.get("opponent", ""),
        "result": last_game.get("result", ""),
        "our_score": last_game.get("our_score", 0),
        "opponent_score": last_game.get("opponent_score", 0),
        "home_or_away": last_game.get("home_or_away", ""),
        "period_type": last_game.get("period_type", "REG"),
        "top_skaters": top_skaters,
        "goalie": goalie,
        "notes": _derive_notes(last_game),
    }

    if games is None:
        games = load_game_log()

    # Deduplicate: skip if the same date+opponent is already the last entry
    if (
        games
        and games[-1].get("date") == entry["date"]
        and games[-1].get("opponent") == entry["opponent"]
    ):
        logger.info(
            "Game log: entry for %s vs %s already exists — skipping",
            entry["date"],
            entry["opponent"],
        )
        return

    games.append(entry)
    games = games[-MAX_GAMES:]  # keep most recent MAX_GAMES

    try:
        with open(GAME_LOG_PATH, "w", encoding="utf-8") as f:
            json.dump(games, f, indent=2)
        logger.info("Game log updated: %d entries", len(games))
    except OSError as e:
        logger.warning("Could not write game log: %s", e)


def format_for_prompt(games: list[dict], n: int = 10) -> str:
    """Format the most recent N games as a compact text block for model prompts.

    Args:
        games: List of game summary dicts from load_game_log().
        n: Number of most-recent games to include.

    Returns:
        Formatted text block, or empty string if games list is empty.
    """
    if not games:
        return ""

    recent = games[-n:]
    lines = [f"=== SEASON GAME LOG (last {len(recent)} games) ==="]

    for g in reversed(recent):  # most recent first
        date = g.get("date", "?")
        opponent = g.get("opponent", "?")
        result = g.get("result", "?")
        os_ = g.get("our_score", 0)
        opp_s = g.get("opponent_score", 0)
        where = f"home vs {opponent}" if g.get("home_or_away") == "home" else f"away at {opponent}"

        skater_parts = []
        for s in g.get("top_skaters", []):
            skater_parts.append(f"{s['name']} {s['goals']}G{s['assists']}A")
        skater_str = ", ".join(skater_parts) if skater_parts else ""

        goalie_str = ""
        goalie = g.get("goalie")
        if goalie and goalie.get("shots_against", 0) > 0:
            goalie_str = f" | {goalie['name']} {goalie['saves']}/{goalie['shots_against']}"

        notes = g.get("notes", [])
        notes_str = f" [{', '.join(notes)}]" if notes else ""

        line = f"  {date}  {result}  {TEAM.abbrev} {os_}, {opponent} {opp_s} ({where})"
        if skater_str:
            line += f"  — {skater_str}"
        line += goalie_str + notes_str
        lines.append(line)

    return "\n".join(lines)


def _goalie_key(name: str) -> str:
    """'D. Levi' and 'Devon Levi' → 'd levi' (first initial + surname)."""
    parts = name.replace(".", " ").split()
    if not parts:
        return ""
    return f"{parts[0][0].lower()} {parts[-1].lower()}" if len(parts) > 1 else parts[0].lower()


def _season_start(date_str: str) -> str:
    """First day of the NHL season that date_str belongs to ('2026-11-14' → '2026-08-01')."""
    try:
        year, month = int(date_str[:4]), int(date_str[5:7])
    except ValueError:
        return ""
    return f"{year if month >= 8 else year - 1}-08-01"


def goalie_starts(games: list[dict], last_game: dict | None = None, n: int = 3) -> dict:
    """Our recent goalie starts this season, from the game log.

    The reported game is added when it isn't in the log yet (it's appended
    only after the email is sent). The logged goalie is the one who played
    the most minutes, i.e. the starter in all but rare cases.

    Returns:
        {"order": [{date, name}] newest first (up to 6),
         "by_goalie": [{name, starts: [{date, opponent, home_or_away, result,
                        our_score, opponent_score, saves, shots}]}]}
        Each goalie's starts are newest first, at most n. Full names win over
        abbreviated ones ("Devon Levi" over "D. Levi").
    """
    entries = list(games)
    if last_game and last_game.get("goalie"):
        if not any(
            g.get("date") == last_game.get("date")
            and g.get("opponent") == last_game.get("opponent")
            for g in entries
        ):
            entries.append(
                {
                    "date": last_game.get("date", ""),
                    "opponent": last_game.get("opponent", ""),
                    "result": last_game.get("result", ""),
                    "our_score": last_game.get("our_score", 0),
                    "opponent_score": last_game.get("opponent_score", 0),
                    "home_or_away": last_game.get("home_or_away", ""),
                    "goalie": {
                        "name": last_game["goalie"].get("name", ""),
                        "saves": last_game["goalie"].get("saves", 0),
                        "shots_against": last_game["goalie"].get("shots_against", 0),
                    },
                }
            )
    if not entries:
        return {"order": [], "by_goalie": []}

    latest = max(e.get("date", "") for e in entries)
    season_start = _season_start(latest)
    season = sorted(
        (e for e in entries if e.get("goalie") and e.get("date", "") >= season_start),
        key=lambda e: e.get("date", ""),
        reverse=True,
    )

    full_names: dict[str, str] = {}
    for e in season:
        name = e["goalie"].get("name", "")
        key = _goalie_key(name)
        first = name.split()[0] if name.split() else ""
        if key and (
            key not in full_names
            or (full_names[key].split()[0].endswith(".") and not first.endswith("."))
        ):
            full_names[key] = name

    order = [
        {"date": e["date"], "name": full_names.get(_goalie_key(e["goalie"]["name"]), "")}
        for e in season[:6]
    ]
    by_goalie: dict[str, list[dict]] = {}
    for e in season:
        key = _goalie_key(e["goalie"].get("name", ""))
        if not key or len(by_goalie.setdefault(key, [])) >= n:
            continue
        by_goalie[key].append(
            {
                "date": e.get("date", ""),
                "opponent": e.get("opponent", ""),
                "home_or_away": e.get("home_or_away", ""),
                "result": e.get("result", ""),
                "our_score": e.get("our_score", 0),
                "opponent_score": e.get("opponent_score", 0),
                "saves": e["goalie"].get("saves", 0),
                "shots": e["goalie"].get("shots_against", 0),
            }
        )
    return {
        "order": order,
        "by_goalie": [{"name": full_names[k], "starts": v} for k, v in by_goalie.items()],
    }
