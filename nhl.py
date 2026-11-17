"""NHL data fetcher for the configured team (config.toml [team] abbrev).

Fetches live data from the public NHL API (no authentication required):
- Most recently completed game result, box score, and team stats
- Current NHL standings (team summary + its full conference)
- Next upcoming game
- Playoff bracket detection and data
"""

import logging
import time
from datetime import date, datetime, timedelta

import requests

import run_report
from config import SETTINGS, TEAM
from team import DIVISION_NAMES, TEAMS

BASE_URL = "https://api-web.nhle.com/v1"
ESPN_INJURIES_URL = "https://site.api.espn.com/apis/site/v2/sports/hockey/nhl/injuries"
TEAM_ABBREV = TEAM.abbrev
TEAM_DISPLAY_NAME = TEAM.name
REQUEST_TIMEOUT = 10  # seconds
TEAM_LOGO_FALLBACK = f"https://assets.nhle.com/logos/nhl/svg/{TEAM_ABBREV}_light.svg"
ROUND_NAMES = {1: "First Round", 2: "Second Round", 3: "Conference Finals", 4: "Stanley Cup Final"}

NHL_TEAM_NAMES = {abbrev: t.name for abbrev, t in TEAMS.items()}

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------


# One session, paced and retried: the NHL API throttles bursts with 429s.
_session = requests.Session()
_response_cache: dict[str, dict] = {}
MIN_REQUEST_INTERVAL = 0.25  # seconds between requests
RETRY_DELAYS = (1, 2, 4, 8)  # seconds before each retry on 429 / 5xx
MAX_RETRY_AFTER = 30  # never wait longer than this for a Retry-After header
_last_request_at = 0.0
_sleep = time.sleep  # swapped out in tests


def clear_cache() -> None:
    """Forget cached responses (each run starts empty; tests call this)."""
    _response_cache.clear()


def _retry_after_seconds(response: requests.Response, default: float) -> float:
    value = response.headers.get("Retry-After", "")
    try:
        return min(max(float(value), 0.0), MAX_RETRY_AFTER)
    except ValueError:
        return default


def _get(url: str) -> dict:
    """GET an NHL API URL and return parsed JSON.

    Uses one shared session, keeps at least MIN_REQUEST_INTERVAL between
    requests, retries 429 and 5xx responses after RETRY_DELAYS (honouring
    Retry-After), and caches successful responses by URL for the run.

    Raises:
        RuntimeError: If the request still fails after the retries.
    """
    global _last_request_at
    if url in _response_cache:
        return _response_cache[url]

    for attempt in range(len(RETRY_DELAYS) + 1):
        wait = MIN_REQUEST_INTERVAL - (time.monotonic() - _last_request_at)
        if wait > 0:
            _sleep(wait)
        _last_request_at = time.monotonic()
        try:
            response = _session.get(url, timeout=REQUEST_TIMEOUT)
            retryable = response.status_code == 429 or response.status_code >= 500
            if retryable and attempt < len(RETRY_DELAYS):
                delay = _retry_after_seconds(response, RETRY_DELAYS[attempt])
                logger.info(
                    "NHL API %s for %s — retry %d/%d in %.0fs",
                    response.status_code,
                    url,
                    attempt + 1,
                    len(RETRY_DELAYS),
                    delay,
                )
                _sleep(delay)
                continue
            response.raise_for_status()
            data = response.json()
        except requests.exceptions.HTTPError as e:
            raise RuntimeError(f"NHL API HTTP error for {url}: {e}") from e
        except requests.exceptions.ConnectionError as e:
            raise RuntimeError(f"NHL API connection error for {url}: {e}") from e
        except requests.exceptions.Timeout as e:
            raise RuntimeError(f"NHL API timeout for {url}: {e}") from e
        except requests.exceptions.RequestException as e:
            raise RuntimeError(f"NHL API request error for {url}: {e}") from e
        _response_cache[url] = data
        return data
    raise RuntimeError(f"NHL API retries exhausted for {url}")  # unreachable


def _safe_get(data, *keys, default=None):
    """Safely traverse a nested dict/list, returning default if any key is missing.

    Args:
        data: The root dictionary or list to traverse.
        *keys: Sequence of keys (str) or indices (int) to follow.
        default: Value to return if traversal fails.

    Returns:
        The value at the given path, or default.
    """
    current = data
    for key in keys:
        try:
            current = current[key]
        except (KeyError, IndexError, TypeError):
            return default
    return current


# ---------------------------------------------------------------------------
# Field parsers
# ---------------------------------------------------------------------------


def _player_name(name_field) -> str:
    """Extract player name string from NHL API name field.

    The API returns names as either a plain string or a dict like {"default": "Leon Draisaitl"}.

    Args:
        name_field: The raw name value from the API.

    Returns:
        Player name as a plain string.
    """
    if isinstance(name_field, dict):
        return name_field.get("default", "Unknown")
    return str(name_field) if name_field else "Unknown"


def _parse_save_pct(goalie: dict) -> float:
    """Extract save percentage from a goalie's stats dict.

    Tries the `savePctg` float field first, then falls back to calculating
    from `saveShotsAgainst` (formatted as "saves/shots", e.g. "23/25").

    Args:
        goalie: Goalie stats dictionary from the box score API.

    Returns:
        Save percentage as a float (e.g. 0.923), or 0.0 if unavailable.
    """
    # Boxscore uses savePctg; club-stats uses savePercentage
    for key in ("savePctg", "savePercentage"):
        pct = goalie.get(key)
        if isinstance(pct, (int, float)) and pct > 0:
            return float(pct)

    raw = goalie.get("saveShotsAgainst", "")
    if raw and "/" in str(raw):
        try:
            saves, shots = str(raw).split("/")
            shots_int = int(shots)
            if shots_int > 0:
                return round(int(saves) / shots_int, 3)
        except (ValueError, ZeroDivisionError):
            pass

    return 0.0


def _parse_saves(goalie: dict) -> tuple[int, int]:
    """Extract saves and shots against from a goalie's stats dict.

    Args:
        goalie: Goalie stats dictionary from the box score API.

    Returns:
        Tuple of (saves, shots_against).
    """
    raw = goalie.get("saveShotsAgainst", "")
    if raw and "/" in str(raw):
        try:
            saves, shots = str(raw).split("/")
            return int(saves), int(shots)
        except ValueError:
            pass
    return 0, 0


def _toi_to_seconds(toi: str) -> int:
    """Convert a MM:SS time-on-ice string to total seconds for sorting.

    Args:
        toi: Time string like "23:14" or "0:00".

    Returns:
        Total seconds as an integer.
    """
    try:
        parts = str(toi).split(":")
        return int(parts[0]) * 60 + int(parts[1])
    except (ValueError, IndexError):
        return 0


def _aggregate_skater_stats(player_group: dict) -> dict:
    """Aggregate team-level stats by summing individual skater records.

    The NHL boxscore API does not always populate teamGameStats. This function
    computes team totals directly from the playerByGameStats entries.

    Args:
        player_group: One of the awayTeam/homeTeam dicts from playerByGameStats,
                      containing "forwards" and "defense" lists.

    Returns:
        Dict with summed hits, pim, pp_goals, blocked shots, takeaways, giveaways.
    """
    skaters = player_group.get("forwards", []) + player_group.get("defense", [])
    return {
        "hits": sum(p.get("hits", 0) for p in skaters),
        "pim": sum(p.get("pim", 0) for p in skaters),
        "pp_goals": sum(p.get("powerPlayGoals", 0) for p in skaters),
        "blocked": sum(p.get("blockedShots", 0) for p in skaters),
        "giveaways": sum(p.get("giveaways", 0) for p in skaters),
        "takeaways": sum(p.get("takeaways", 0) for p in skaters),
    }


def _build_team_stats(boxscore: dict, we_are_away: bool, right_rail: dict | None = None) -> dict:
    """Build the team stats comparison dict from boxscore data.

    SOG comes from the top-level awayTeam/homeTeam objects (authoritative).
    Hits, blocks, PP goals and PIM are aggregated from individual player records.
    When the right-rail teamGameStats are available they add faceoff win % and
    power play as goals/opportunities, and replace PIM if it differs (the skater
    sum misses goalie and bench minors).

    Args:
        boxscore: Full box score dict from the gamecenter API.
        we_are_away: True if our team are the away team.
        right_rail: Optional right-rail payload from fetch_right_rail().

    Returns:
        Dict with "ours" and "opponent" keys, each containing:
        sog, pp_goals, hits, pim, blocked as strings, plus faceoffs ("40.4%")
        and power_play ("1/2") when available.
    """
    away_team = boxscore.get("awayTeam", {})
    home_team = boxscore.get("homeTeam", {})

    our_sog = str(away_team.get("sog", "—") if we_are_away else home_team.get("sog", "—"))
    opp_sog = str(home_team.get("sog", "—") if we_are_away else away_team.get("sog", "—"))

    player_stats = boxscore.get("playerByGameStats", {})
    our_key = "awayTeam" if we_are_away else "homeTeam"
    opp_key = "homeTeam" if we_are_away else "awayTeam"

    o_agg = _aggregate_skater_stats(player_stats.get(our_key, {}))
    p_agg = _aggregate_skater_stats(player_stats.get(opp_key, {}))

    stats = {
        "ours": {
            "sog": our_sog,
            "pp_goals": str(o_agg["pp_goals"]),
            "hits": str(o_agg["hits"]),
            "pim": str(o_agg["pim"]),
            "blocked": str(o_agg["blocked"]),
        },
        "opponent": {
            "sog": opp_sog,
            "pp_goals": str(p_agg["pp_goals"]),
            "hits": str(p_agg["hits"]),
            "pim": str(p_agg["pim"]),
            "blocked": str(p_agg["blocked"]),
        },
    }

    # Right-rail categories: {category: {"ours": value, "opponent": value}}
    rr: dict[str, dict] = {}
    for cat in (right_rail or {}).get("teamGameStats", []) or []:
        away_v, home_v = cat.get("awayValue"), cat.get("homeValue")
        if away_v is None or home_v is None:
            continue
        rr[cat.get("category", "")] = {
            "ours": away_v if we_are_away else home_v,
            "opponent": home_v if we_are_away else away_v,
        }

    for side in ("ours", "opponent"):
        fo = rr.get("faceoffWinningPctg", {}).get(side)
        if isinstance(fo, (int, float)):
            stats[side]["faceoffs"] = f"{fo * 100:.1f}%"
        pp = rr.get("powerPlay", {}).get(side)
        if isinstance(pp, str) and "/" in pp:
            stats[side]["power_play"] = pp
        pim = rr.get("pim", {}).get(side)
        if isinstance(pim, (int, float)) and str(int(pim)) != stats[side]["pim"]:
            logger.info(
                "PIM (%s): right-rail %s replaces skater sum %s", side, pim, stats[side]["pim"]
            )
            stats[side]["pim"] = str(int(pim))
    return stats


# ---------------------------------------------------------------------------
# API fetch functions
# ---------------------------------------------------------------------------


def fetch_week_schedule(date_str: str = "now") -> list[dict]:
    """Fetch our team's schedule for a given week.

    Args:
        date_str: Either "now" or a date string in YYYY-MM-DD format for the
                  Monday of the desired week.

    Returns:
        List of game objects from the API response.
    """
    url = f"{BASE_URL}/club-schedule/{TEAM_ABBREV}/week/{date_str}"
    data = _get(url)
    return data.get("games", [])


def fetch_team_injuries() -> list[dict]:
    """Fetch the current our injury list from the ESPN injuries API.

    Returns real-time IR and out designations — more reliable than news scraping
    since it reflects the official roster status.

    Returns:
        List of dicts with player, position, status, injury (ESPN's injury type,
        "" when ESPN gives none or "Undisclosed") and expected_return (ISO date
        from ESPN's estimate, "" when absent). Returns [] on any error.
    """
    try:
        response = requests.get(
            ESPN_INJURIES_URL, timeout=REQUEST_TIMEOUT, headers={"User-Agent": "NHLDaily/1.0"}
        )
        response.raise_for_status()
        data = response.json()
    except Exception as e:
        logger.warning("ESPN injuries fetch failed: %s", e)
        run_report.record("Injury Report", "ESPN data unavailable")
        return []

    injuries = []
    for team in data.get("injuries", []):
        if team.get("displayName") != TEAM_DISPLAY_NAME:
            continue
        for entry in team.get("injuries", []):
            athlete = entry.get("athlete", {})
            name = athlete.get("displayName", "")
            status = entry.get("status", "")
            details = entry.get("details") or {}
            injury = str(details.get("type") or "").strip()
            if injury.lower() in ("undisclosed", "not specified", "other"):
                injury = ""
            expected_return = str(details.get("returnDate") or "")[:10]

            position = athlete.get("position", {}).get("abbreviation", "?")
            injuries.append(
                {
                    "player": name,
                    "position": position,
                    "injury": injury,
                    "status": status,
                    "expected_return": expected_return,
                }
            )
        break

    logger.info("Fetched %d our injuries from ESPN", len(injuries))
    return injuries


LOCAL_TZ = SETTINGS.local_tz  # "last night", "tonight": the team's home zone by default
DISPLAY_TZ = SETTINGS.display_tz  # start times shown in the email
RECENT_GAME_WINDOW_DAYS = 2


def local_now() -> datetime:
    """Now in LOCAL_TZ (config [time] local_timezone): the one clock for anything a reader sees or that
    selects data. Log timestamps may use their own clock; tests/test_clock.py
    fails if another content-time clock call appears."""
    return datetime.now(LOCAL_TZ)


def local_today() -> date:
    """Today's date in LOCAL_TZ (config [time] local_timezone)."""
    return local_now().date()


def reference_date(last_game_date: date | None, today: date | None = None) -> date:
    """The one date all relative-day wording in a run is measured from.

    The later of today in LOCAL_TZ and the day after the reported game, so a run
    that starts just before local midnight on game night still says "last
    night" and "tonight" — the email is read the next morning.
    """
    today = today or local_today()
    if last_game_date is None:
        return today
    return max(today, last_game_date + timedelta(days=1))


def _parse_date(date_str: str) -> date | None:
    try:
        return date.fromisoformat(str(date_str)[:10])
    except ValueError:
        return None


def format_display_time(start_utc: str) -> str:
    """Format a UTC start time for display in DISPLAY_TZ, e.g. "Sun 15 Nov, 01:00 CET".

    Returns "" if the timestamp is missing or unparseable.
    """
    if not start_utc:
        return ""
    try:
        dt = datetime.fromisoformat(start_utc.replace("Z", "+00:00")).astimezone(DISPLAY_TZ)
    except ValueError:
        return ""
    return f"{dt:%a} {dt.day} {dt:%b}, {dt:%H:%M} {dt.tzname()}"


def past_day_phrase(days_ago: int | None, weekday: str, date_label: str) -> str:
    """Plain-words phrase for when a past game was played, relative to today (LOCAL_TZ).

    0 → "earlier today", 1 → "last night", 2+ → "on Wednesday, November 11 (3 days ago)".
    """
    if days_ago == 0:
        return "earlier today"
    if days_ago == 1:
        return "last night"
    if days_ago is None:
        return f"on {weekday}, {date_label}".strip(", ")
    return f"on {weekday}, {date_label} ({days_ago} days ago)"


def _date_label(d: date) -> str:
    return f"{d:%B} {d.day}"


def latest_completed_game() -> dict | None:
    """Return the most recent completed our game from the last couple of days.

    "Completed" means gameState == "OFF", matching _find_last_completed_game()
    so the gate and the data fetch always agree on which game is "last night's".
    Dates are compared in local time (config [time]), not UTC, so the result doesn't depend
    on what time of day the job happens to run.

    Returns:
        {"date": "YYYY-MM-DD", "opponent": "ABC"} for the latest completed game
        within RECENT_GAME_WINDOW_DAYS, or None if there isn't one.

    Raises:
        RuntimeError: If the schedule can't be fetched.
    """
    today = datetime.now(LOCAL_TZ).date()
    earliest = today - timedelta(days=RECENT_GAME_WINDOW_DAYS)

    games = fetch_month_schedule(today.isoformat())
    if earliest.month != today.month:
        games = fetch_month_schedule(earliest.isoformat()) + games

    recent = [
        g
        for g in games
        if g.get("gameState") == "OFF"
        and earliest.isoformat() <= g.get("gameDate", "") <= today.isoformat()
    ]
    if not recent:
        return None
    game = max(recent, key=lambda g: (g.get("gameDate", ""), g.get("startTimeUTC", "")))
    away = _safe_get(game, "awayTeam", "abbrev", default="")
    home = _safe_get(game, "homeTeam", "abbrev", default="")
    return {"date": game.get("gameDate", ""), "opponent": home if away == TEAM_ABBREV else away}


def fetch_month_schedule(date_str: str = "now") -> list[dict]:
    """Fetch our team's schedule for a given month.

    Using the month endpoint is more reliable than the week endpoint for
    finding the most recently completed game, since week boundaries can
    leave recent games in a "previous week" bucket.

    Args:
        date_str: Either "now" or a date string in YYYY-MM-DD format for any
                  day within the desired month.

    Returns:
        List of game objects from the API response.
    """
    return fetch_team_month_schedule(TEAM_ABBREV, date_str)


def fetch_team_month_schedule(team_abbrev: str, date_str: str = "now") -> list[dict]:
    """Fetch a given team's schedule for a given month.

    Args:
        team_abbrev: Three-letter team abbreviation, e.g. "EDM".
        date_str: Either "now" or a date string in YYYY-MM-DD format for any
                  day within the desired month.

    Returns:
        List of game objects from the API response.
    """
    # The endpoint takes "now" or "YYYY-MM"; a full "YYYY-MM-DD" returns 404.
    if date_str != "now":
        date_str = date_str[:7]
    url = f"{BASE_URL}/club-schedule/{team_abbrev}/month/{date_str}"
    data = _get(url)
    return data.get("games", [])


def fetch_team_season_schedule(team_abbrev: str) -> list[dict]:
    """Fetch a given team's full current season schedule.

    Returns all games for the season (completed + upcoming). Used for
    streak computation so that runs spanning multiple months are captured.

    Args:
        team_abbrev: Three-letter team abbreviation, e.g. "EDM".

    Returns:
        List of game objects from the API response.
    """
    url = f"{BASE_URL}/club-schedule-season/{team_abbrev}/now"
    data = _get(url)
    return data.get("games", [])


def fetch_boxscore(game_id: int) -> dict:
    """Fetch the full box score for a specific game.

    Args:
        game_id: NHL game ID (e.g. 2024020855).

    Returns:
        Raw box score dictionary from the API.
    """
    url = f"{BASE_URL}/gamecenter/{game_id}/boxscore"
    return _get(url)


def fetch_game_roster_names(game_id: int) -> dict[int, str]:
    """Return {playerId: "First Last"} for every player dressed in a game.

    The boxscore and three-stars payloads only carry abbreviated names
    ("T. Jarry"), which the model will happily mis-expand ("Totem Jarry").
    The play-by-play endpoint's rosterSpots has full names for both teams.
    Returns {} on any failure so callers fall back to the abbreviated names.
    """
    try:
        data = _get(f"{BASE_URL}/gamecenter/{game_id}/play-by-play")
    except RuntimeError as e:
        logger.warning("Roster names unavailable for game %s: %s", game_id, e)
        return {}
    names: dict[int, str] = {}
    for spot in data.get("rosterSpots", []) or []:
        pid = spot.get("playerId")
        full = _player_name_from_parts(spot)
        if pid and full != "Unknown":
            names[pid] = full
    return names


def fetch_right_rail(game_id: int) -> dict:
    """Fetch the gamecenter right-rail payload (teamGameStats: faceoffs, PP, PIM, ...).

    Returns {} on failure so callers fall back to boxscore-derived stats.
    """
    try:
        return _get(f"{BASE_URL}/gamecenter/{game_id}/right-rail")
    except RuntimeError as e:
        logger.warning("Right-rail stats unavailable for game %s: %s", game_id, e)
        run_report.record("Faceoffs and power play", run_report.NHL_UNAVAILABLE)
        return {}


def fetch_standings() -> list[dict]:
    """Fetch current NHL standings.

    Returns:
        List of team standing objects from the API response.
    """
    url = f"{BASE_URL}/standings/now"
    data = _get(url)
    return data.get("standings", [])


def fetch_playoff_bracket(season_id: int) -> dict | None:
    """Fetch the playoff bracket for a given NHL season.

    Args:
        season_id: Full season ID, e.g. 20242025. The playoff year (last 4
                   digits) is extracted for the URL.

    Returns:
        Parsed bracket dict with a "rounds" list, or None if unavailable.
    """
    year = str(season_id)[4:]  # e.g. 20242025 → "2025"
    url = f"{BASE_URL}/playoff-bracket/{year}"
    try:
        return _get(url)
    except RuntimeError as e:
        logger.warning("Playoff bracket unavailable: %s", e)
        return None


def fetch_landing(game_id: int) -> dict:
    """Fetch the gamecenter landing page data for a specific game.

    Contains scoring summary, three stars, and other rich game details
    not available in the boxscore endpoint.

    Args:
        game_id: NHL game ID (e.g. 2024020855).

    Returns:
        Raw landing dictionary from the API.
    """
    url = f"{BASE_URL}/gamecenter/{game_id}/landing"
    return _get(url)


def fetch_season_schedule() -> list[dict]:
    """Fetch our team's full current season schedule.

    Returns all games for the season, including completed, upcoming, and
    in-progress. Used for season series, recent form, and upcoming schedule.

    Returns:
        List of game objects from the API response.
    """
    url = f"{BASE_URL}/club-schedule-season/{TEAM_ABBREV}/now"
    data = _get(url)
    return data.get("games", [])


def fetch_club_stats() -> dict:
    """Fetch current season stats for all our skaters and goalies.

    Used for the top scorers leaderboard and milestone watch.

    Returns:
        Raw club stats dictionary with "skaters" and "goalies" lists.
    """
    url = f"{BASE_URL}/club-stats/{TEAM_ABBREV}/now"
    return _get(url)


def fetch_club_stats_playoffs(season_id: int) -> dict:
    """Fetch playoff stats for all our skaters and goalies.

    Args:
        season_id: Full season ID, e.g. 20252026.

    Returns:
        Raw club stats dictionary with "skaters" and "goalies" lists,
        or an empty dict if unavailable.
    """
    url = f"{BASE_URL}/club-stats/{TEAM_ABBREV}/{season_id}/3"
    try:
        return _get(url)
    except RuntimeError as e:
        logger.warning("Playoff club stats unavailable: %s", e)
        return {}


def fetch_opponent_club_stats(abbrev: str) -> dict:
    """Fetch current season stats for all skaters and goalies on a given team.

    Args:
        abbrev: NHL team abbreviation, e.g. "VGK".

    Returns:
        Raw club stats dictionary with "skaters" and "goalies" lists.
    """
    url = f"{BASE_URL}/club-stats/{abbrev}/now"
    return _get(url)


def fetch_team_prospects() -> list[dict]:
    """Fetch the current list of our prospects from the NHL API.

    Returns:
        Flat list of prospect dicts (forwards + defensemen + goalies combined),
        each tagged with a '_position_group' key. Returns [] on any error.
    """
    url = f"{BASE_URL}/prospects/{TEAM_ABBREV}"
    try:
        data = _get(url)
        prospects = []
        for group in ("forwards", "defensemen", "goalies"):
            for p in data.get(group, []):
                p["_position_group"] = group
                # Normalise 'id' → 'playerId' so downstream code is consistent
                if "playerId" not in p and "id" in p:
                    p["playerId"] = p["id"]
                prospects.append(p)
        return prospects
    except RuntimeError as e:
        logger.warning("Could not fetch our prospects: %s", e)
        return []


def fetch_prospect_landing(player_id: int) -> dict:
    """Fetch the player landing page for a prospect.

    Args:
        player_id: NHL player ID.

    Returns:
        Raw landing dict from the API.
    """
    url = f"{BASE_URL}/player/{player_id}/landing"
    return _get(url)


def _extract_prospect_stats(landing: dict) -> dict | None:
    """Extract current regular-season stats from a player's landing page.

    Handles multi-team seasons by taking the entry with the most games played.
    Returns skater stats (G/A/PTS/+/-) or goalie stats (W/GAA/SV%) depending
    on the player's position.

    Args:
        landing: Raw response from fetch_prospect_landing().

    Returns:
        Stats dict, or None if no current-season data or 0 GP.
    """
    season_totals = landing.get("seasonTotals", [])
    if not season_totals:
        return None

    reg_season = [s for s in season_totals if s.get("gameTypeId") == 2]
    if not reg_season:
        return None

    # Most recent season
    max_season = max(s.get("season", 0) for s in reg_season)
    current = sorted(
        [s for s in reg_season if s.get("season", 0) == max_season],
        key=lambda s: s.get("gamesPlayed", 0),
        reverse=True,
    )[0]

    gp = current.get("gamesPlayed", 0)
    if gp == 0:
        return None

    team_name = _safe_get(current, "teamName", "default") or ""
    league = current.get("leagueAbbrev", "")
    position = landing.get("position", "")

    base = {"league": league, "team": team_name, "season": max_season, "gp": gp}

    if position == "G":
        return {
            **base,
            "wins": current.get("wins", 0),
            "gaa": round(current.get("goalsAgainstAvg", 0.0), 2),
            "sv_pct": round(current.get("savePctg", 0.0), 3),
            "shutouts": current.get("shutouts", 0),
        }
    return {
        **base,
        "goals": current.get("goals", 0),
        "assists": current.get("assists", 0),
        "points": current.get("points", 0),
        "plus_minus": current.get("plusMinus", 0),
    }


def _extract_ahl_goalie_stats(landing: dict) -> dict | None:
    """Extract current AHL-only regular-season stats for a goalie.

    Filters exclusively to AHL entries so call-up NHL games are ignored.
    Returns None if the goalie has no AHL games this season.

    Args:
        landing: Raw response from fetch_prospect_landing().

    Returns:
        Goalie stats dict (same format as _extract_prospect_stats for goalies),
        or None if no AHL games played this season.
    """
    season_totals = landing.get("seasonTotals", [])
    ahl = [s for s in season_totals if s.get("gameTypeId") == 2 and s.get("leagueAbbrev") == "AHL"]
    if not ahl:
        return None

    max_season = max(s.get("season", 0) for s in ahl)
    current = sorted(
        [s for s in ahl if s.get("season", 0) == max_season],
        key=lambda s: s.get("gamesPlayed", 0),
        reverse=True,
    )[0]

    gp = current.get("gamesPlayed", 0)
    if gp == 0:
        return None

    return {
        "league": "AHL",
        "team": _safe_get(current, "teamName", "default") or "",
        "season": max_season,
        "gp": gp,
        "wins": current.get("wins", 0),
        "gaa": round(current.get("goalsAgainstAvg", 0.0), 2),
        "sv_pct": round(current.get("savePctg", 0.0), 3),
        "shutouts": current.get("shutouts", 0),
    }


def get_prospects_data() -> list[dict]:
    """Fetch and compile current-season stats for all our prospects.

    Fetches our team prospect list, then retrieves each player's landing
    page to extract their stats in whatever league they're currently playing.

    Returns:
        List of prospect dicts with name, position, league, team, and stats.
        Skaters sorted by points desc, goalies appended sorted by sv_pct desc.
    """
    prospects_raw = fetch_team_prospects()
    if not prospects_raw:
        return []

    # Exclude players currently on the active NHL roster — they are not prospects.
    try:
        roster_data = _get(f"{BASE_URL}/roster/{TEAM_ABBREV}/current")
        nhl_roster_ids: set[int] = set()
        for group in ("forwards", "defensemen", "goalies"):
            for player in roster_data.get(group, []):
                pid = player.get("id")
                if pid:
                    nhl_roster_ids.add(pid)
        logger.info("Active NHL roster: %d players excluded from prospects", len(nhl_roster_ids))
    except RuntimeError as e:
        logger.warning("Could not fetch active roster for filtering: %s", e)
        nhl_roster_ids = set()

    skaters: list[dict] = []
    goalies: list[dict] = []

    for p in prospects_raw:
        player_id = p.get("playerId")
        if not player_id:
            continue
        if player_id in nhl_roster_ids:
            continue  # on active NHL roster, not a prospect
        try:
            landing = fetch_prospect_landing(player_id)
        except RuntimeError as e:
            logger.warning("Could not fetch prospect landing %s: %s", player_id, e)
            continue

        stats = _extract_prospect_stats(landing)

        first = (
            _safe_get(p, "firstName", "default") or _safe_get(landing, "firstName", "default") or ""
        )
        last = (
            _safe_get(p, "lastName", "default") or _safe_get(landing, "lastName", "default") or ""
        )
        position = landing.get("position", p.get("positionCode", ""))

        # Always include goalies even if stats are unavailable — they are team-owned
        # and the user wants visibility on all goaltending depth in every league.
        if not stats:
            if position == "G":
                stats = {
                    "league": "",
                    "team": "",
                    "season": 0,
                    "gp": 0,
                    "wins": 0,
                    "gaa": 0.0,
                    "sv_pct": 0.0,
                    "shutouts": 0,
                }
            else:
                continue

        record = {
            "name": f"{first} {last}".strip(),
            "player_id": player_id,
            "position": position,
            "position_group": p.get("_position_group", ""),
            "headshot": landing.get("headshot", ""),
            **stats,
        }

        if position == "G":
            goalies.append(record)
        else:
            skaters.append(record)

    skaters.sort(key=lambda x: (x.get("points", 0), x.get("goals", 0)), reverse=True)
    goalies.sort(key=lambda x: x.get("sv_pct", 0.0), reverse=True)

    # Supplement with Condors goalies not already in the prospects list.
    # club-stats/EDM/now returns all org-affiliated goalies including AHL vets.
    try:
        org_goalies = _get(f"{BASE_URL}/club-stats/{TEAM_ABBREV}/now").get("goalies", [])
        existing_ids = {g["player_id"] for g in goalies}
        for og in org_goalies:
            pid = og.get("playerId")
            if not pid or pid in existing_ids or pid in nhl_roster_ids:
                continue
            try:
                landing = fetch_prospect_landing(pid)
            except RuntimeError:
                continue
            stats = _extract_ahl_goalie_stats(landing)
            if not stats:
                continue  # not playing in AHL this season
            first = _safe_get(landing, "firstName", "default") or ""
            last = _safe_get(landing, "lastName", "default") or ""
            goalies.append(
                {
                    "name": f"{first} {last}".strip(),
                    "player_id": pid,
                    "position": "G",
                    "position_group": "goalies",
                    "headshot": landing.get("headshot", ""),
                    **stats,
                }
            )
        goalies.sort(key=lambda x: x.get("sv_pct", 0.0), reverse=True)
    except RuntimeError as e:
        logger.warning("Could not supplement org goalies: %s", e)

    logger.info("Prospects: %d skaters, %d goalies", len(skaters), len(goalies))
    return skaters + goalies


def fetch_today_schedule(ref_date: date | None = None) -> list[dict]:
    """Fetch today's league-wide NHL schedule.

    Args:
        ref_date: The run's reference date ("tonight" in the email); defaults
            to today in local time.

    Returns:
        List of game objects for that date, or an empty list if unavailable.
    """
    url = f"{BASE_URL}/schedule/now"
    try:
        data = _get(url)
        today_str = (ref_date or local_today()).isoformat()
        for day in data.get("gameWeek", []):
            if day.get("date") == today_str:
                return day.get("games", [])
        return []
    except RuntimeError as e:
        logger.warning("Could not fetch today's schedule: %s", e)
        run_report.record("Tonight's race games", run_report.NHL_UNAVAILABLE)
        return []


# ---------------------------------------------------------------------------
# Schedule helpers
# ---------------------------------------------------------------------------


def _find_last_completed_game(games: list[dict]) -> dict | None:
    """Find the most recently completed our game from a schedule list.

    A completed game has gameState == "OFF".

    Args:
        games: List of game objects from the schedule endpoint.

    Returns:
        The most recent completed game dict, or None if not found.
    """
    completed = [g for g in games if g.get("gameState") == "OFF"]
    if not completed:
        return None
    return sorted(completed, key=lambda g: g.get("gameDate", ""), reverse=True)[0]


def _find_next_game(games: list[dict]) -> dict | None:
    """Find the next upcoming our game from a schedule list.

    An upcoming game has gameState == "FUT" or "PRE".

    Args:
        games: List of game objects from the schedule endpoint.

    Returns:
        The soonest upcoming game dict, or None if not found.
    """
    upcoming = [g for g in games if g.get("gameState") in ("FUT", "PRE")]
    if not upcoming:
        return None
    return sorted(upcoming, key=lambda g: g.get("gameDate", ""))[0]


def _is_playoff_season(games: list[dict]) -> bool:
    """Determine whether the current schedule contains playoff games.

    Playoff games have gameType == 3; regular season is gameType == 2.

    Args:
        games: List of game objects from the schedule endpoint.

    Returns:
        True if any game has gameType == 3.
    """
    return any(g.get("gameType") == 3 for g in games)


# ---------------------------------------------------------------------------
# Data extractors
# ---------------------------------------------------------------------------


def _extract_last_game_info(
    game: dict,
    boxscore: dict,
    name_lookup: dict[int, str] | None = None,
    right_rail: dict | None = None,
    ref_date: date | None = None,
) -> dict:
    """Build the last_game sub-dict from raw API data.

    Extracts score, result, top skaters, all goalies, and team game stats
    (SOG, power play, hits, PIM, faceoff %).

    Args:
        game: Game object from the schedule API.
        boxscore: Box score object from the gamecenter API.

    Returns:
        Structured last_game dictionary.
    """
    game_id = game.get("id")
    date = game.get("gameDate", "Unknown")

    away = game.get("awayTeam", {})
    home = game.get("homeTeam", {})

    away_abbrev = away.get("abbrev", "")
    home_abbrev = home.get("abbrev", "")

    if away_abbrev == TEAM_ABBREV:
        home_or_away = "away"
        our_score = away.get("score", 0)
        opponent_score = home.get("score", 0)
        opponent = home_abbrev
        our_key = "awayTeam"
        we_are_away = True
    else:
        home_or_away = "home"
        our_score = home.get("score", 0)
        opponent_score = away.get("score", 0)
        opponent = away_abbrev
        our_key = "homeTeam"
        we_are_away = False

    # Determine result
    period_type = (
        _game_period_type(game)
        if (game.get("gameOutcome") or game.get("periodDescriptor"))
        else _game_period_type(boxscore)
    )
    if our_score > opponent_score:
        result = "W"
    elif period_type in ("OT", "SO"):
        result = "OTL"
    else:
        result = "L"

    # --- Skaters ---
    player_stats = boxscore.get("playerByGameStats", {})
    our_player_stats = player_stats.get(our_key, {})

    forwards = our_player_stats.get("forwards", [])
    defense = our_player_stats.get("defense", [])
    all_skaters = forwards + defense
    all_skaters.sort(
        key=lambda p: (
            p.get("points", 0),
            p.get("goals", 0),
            _toi_to_seconds(p.get("toi", "0:00")),
        ),
        reverse=True,
    )

    top_skaters = []
    for skater in all_skaters[:3]:
        top_skaters.append(
            {
                "name": _full_player_name(skater, name_lookup),
                "goals": skater.get("goals", 0),
                "assists": skater.get("assists", 0),
                "points": skater.get("points", 0),
                "toi": skater.get("toi", "0:00"),
            }
        )

    # --- All goalies (sorted starter first by TOI) ---
    raw_goalies = our_player_stats.get("goalies", [])
    raw_goalies.sort(key=lambda g: _toi_to_seconds(g.get("toi", "0:00")), reverse=True)

    goalies = []
    for g in raw_goalies:
        if _toi_to_seconds(g.get("toi", "0:00")) == 0:
            continue  # goalie never entered the game
        saves, shots_against = _parse_saves(g)
        goalies.append(
            {
                "player_id": g.get("playerId"),
                "name": _full_player_name(g, name_lookup),
                "saves": saves,
                "shots_against": shots_against,
                "save_pct": _parse_save_pct(g),
                "decision": g.get("decision", ""),
                "toi": g.get("toi", "0:00"),
            }
        )

    # --- Opponent goalie (starter by TOI) ---
    opponent_key = "homeTeam" if we_are_away else "awayTeam"
    opp_stats = player_stats.get(opponent_key, {})
    raw_opp_goalies = opp_stats.get("goalies", [])
    raw_opp_goalies.sort(key=lambda g: _toi_to_seconds(g.get("toi", "0:00")), reverse=True)
    opponent_goalie = None
    for g in raw_opp_goalies:
        if _toi_to_seconds(g.get("toi", "0:00")) == 0:
            continue
        saves, shots_against = _parse_saves(g)
        opponent_goalie = {
            "player_id": g.get("playerId"),
            "name": _full_player_name(g, name_lookup),
            "saves": saves,
            "shots_against": shots_against,
        }
        break  # starter only

    # Saves/shots for every goalie who played, by playerId (for the Three Stars)
    goalie_lines: dict = {}
    for side in ("awayTeam", "homeTeam"):
        for g in player_stats.get(side, {}).get("goalies", []):
            if g.get("playerId") and _toi_to_seconds(g.get("toi", "0:00")) > 0:
                saves, shots_against = _parse_saves(g)
                goalie_lines[g["playerId"]] = {"saves": saves, "shots": shots_against}

    # --- Team game stats ---
    team_stats = _build_team_stats(boxscore, we_are_away, right_rail)

    recap_link_path = game.get("gameCenterLink", "")
    recap_link = f"https://www.nhl.com{recap_link_path}" if recap_link_path else None

    return {
        "game_id": game_id,
        "date": date,
        "opponent": opponent,
        "home_or_away": home_or_away,
        "our_score": our_score,
        "opponent_score": opponent_score,
        "result": result,
        "period_type": period_type,  # REG / OT / SO
        **_last_game_when_where(date, game, boxscore, ref_date),
        "top_skaters": top_skaters,
        "goalies": goalies,
        "goalie": goalies[0] if goalies else None,  # backwards compat for digest.py
        "opponent_goalie": opponent_goalie,
        "team_stats": team_stats,
        "recap_link": recap_link,
        # Populated later by get_team_data after landing + season-schedule fetches
        "scoring_summary": [],
        "three_stars": [],
        "season_series": None,
        "game_winning_goal": None,
        "decided_in_shootout": period_type == "SO",
        "shutout": _shutout_info(goalies) if opponent_score == 0 else None,
        "goalie_lines": goalie_lines,
        "previous_meeting": None,
    }


def _shutout_info(goalies: list[dict]) -> dict | None:
    """Shutout credit for our team goalie(s) who played: names, saves, shots."""
    played = [g for g in goalies if g.get("shots_against", 0) or g.get("saves", 0)]
    played = played or goalies[:1]
    if not played:
        return None
    return {
        "goalies": [g.get("name", "") for g in played],
        "saves": sum(g.get("saves", 0) for g in played),
        "shots": sum(g.get("shots_against", 0) for g in played),
    }


def _last_game_when_where(
    game_date_str: str, game: dict, boxscore: dict, ref_date: date | None = None
) -> dict:
    """Weekday, days before ref_date (the run's reference date), and venue name/city."""
    out: dict = {}
    game_date = _parse_date(game_date_str)
    if game_date:
        out["weekday"] = f"{game_date:%A}"
        out["days_ago"] = ((ref_date or local_today()) - game_date).days
        out["date_label"] = _date_label(game_date)
    venue = _safe_get(game, "venue", "default") or _safe_get(boxscore, "venue", "default") or ""
    if venue:
        out["venue"] = venue
    city = _safe_get(boxscore, "venueLocation", "default") or ""
    if city:
        out["venue_city"] = city
    return out


def _extract_game_winning_goal(last_game: dict) -> dict | None:
    """The goal that put the winning team one ahead of the loser's final total.

    Returns:
        Dict with scorer, team, period_label, time, assists, strength — or None
        for a shootout (decided_in_shootout covers that) or if it can't be found.
    """
    if last_game.get("period_type") == "SO":
        return None
    o, p = last_game.get("our_score", 0), last_game.get("opponent_score", 0)
    if o == p:
        return None
    winner = TEAM_ABBREV if o > p else last_game.get("opponent", "")
    target = min(o, p) + 1
    count = 0
    for period in last_game.get("scoring_summary", []):
        for goal in period.get("goals", []):
            if goal.get("team") == winner:
                count += 1
                if count == target:
                    return {
                        "scorer": goal.get("scorer", ""),
                        "team": winner,
                        "period_label": period.get("period_label", ""),
                        "time": goal.get("time", ""),
                        "phase": goal.get("phase", ""),
                        "assists": goal.get("assists", []),
                        "strength": goal.get("strength", "EV"),
                    }
    return None


def _extract_standings_info(standings: list[dict], our_streak: str = "—") -> dict | None:
    """Find and extract our team's standing from the full standings list.

    Args:
        standings: Full list of team standing objects from the API.
        our_streak: Pre-computed streak string (OTL treated as L). When
            provided this replaces the streak_code/streak_count from the API.

    Returns:
        Structured standings dictionary, or None if our team not found.
    """
    for team in standings:
        abbrev = _safe_get(team, "teamAbbrev", "default") or team.get("teamAbbrev", "")
        if abbrev == TEAM_ABBREV:
            return {
                "wins": team.get("wins", 0),
                "losses": team.get("losses", 0),
                "ot_losses": team.get("otLosses", 0),
                "points": team.get("points", 0),
                "point_pct": round(team.get("pointPctg", 0.0), 3),
                "division_rank": team.get("divisionSequence", 0),
                "streak": our_streak,
            }
    return None


def _games_played_words(our_gp: int, other_gp: int) -> str:
    diff = other_gp - our_gp
    if diff == 0:
        return "with equal games played"
    n = abs(diff)
    plural = "s" if n != 1 else ""
    if diff > 0:
        return f"with {n} game{plural} in hand"
    return f"having played {n} more game{plural}"


def _extract_division_gap(standings: list[dict]) -> dict | None:
    """our team's place in its division and the points gap to the teams around it.

    Returns:
        Dict with division, rank, points, gp, and "above"/"below" neighbours
        ({abbrev, rank, points, gp}) — the leader when we are not first,
        the team directly below otherwise; None if our team is not found.
    """
    edm = next((t for t in standings if _safe_get(t, "teamAbbrev", "default") == TEAM_ABBREV), None)
    if not edm:
        return None
    div = edm.get("divisionAbbrev", "")
    teams = sorted(
        (t for t in standings if t.get("divisionAbbrev", "") == div),
        key=lambda t: t.get("divisionSequence", 99),
    )

    def _entry(t: dict) -> dict:
        return {
            "abbrev": _safe_get(t, "teamAbbrev", "default") or "",
            "rank": t.get("divisionSequence", 0),
            "points": t.get("points", 0),
            "gp": t.get("gamesPlayed", 0),
        }

    me = _entry(edm)
    idx = next(i for i, t in enumerate(teams) if t is edm)
    gap = {
        "division": DIVISION_NAMES.get(div, edm.get("divisionName", div)),
        "rank": me["rank"],
        "points": me["points"],
        "gp": me["gp"],
    }
    if idx > 0:
        gap["above"] = _entry(teams[0])
    if idx + 1 < len(teams):
        gap["below"] = _entry(teams[idx + 1])
    return gap


def division_gap_text(gap: dict | None) -> str:
    """'Pacific: 1st, 4 points ahead of VGK with equal games played.'"""
    if not gap or not gap.get("rank"):
        return ""

    def _ord(n: int) -> str:
        suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
        return f"{n}{suffix}"

    def _pts(n: int) -> str:
        return f"{n} point{'s' if n != 1 else ''}"

    parts = []
    above, below = gap.get("above"), gap.get("below")
    if above:
        diff = above["points"] - gap["points"]
        rel = (
            f"level on points with {above['abbrev']}"
            if diff == 0
            else (f"{_pts(diff)} behind {above['abbrev']}")
        )
        parts.append(f"{rel} (1st) {_games_played_words(gap['gp'], above['gp'])}")
    if below:
        diff = gap["points"] - below["points"]
        rel = (
            f"level on points with {below['abbrev']}"
            if diff == 0
            else (f"{_pts(diff)} ahead of {below['abbrev']}")
        )
        label = f" ({_ord(below['rank'])})" if above else ""
        parts.append(f"{rel}{label} {_games_played_words(gap['gp'], below['gp'])}")
    text = f"{gap['division']}: {_ord(gap['rank'])}"
    if parts:
        text += ", " + "; ".join(parts)
    return text + "."


def _compute_streak_otl_as_loss(games: list[dict], team_abbrev: str) -> str:
    """Compute the current streak treating OTL identically to a regulation loss.

    Walks completed games (gameState "OFF") from most recent to oldest,
    counting consecutive wins or losses (regulation + OT/SO). Returns a
    string like "W4" or "L3", or "—" if no completed games are found.

    Args:
        games: List of game objects from the team's monthly schedule.
        team_abbrev: Three-letter abbreviation of the team to compute for.

    Returns:
        Streak string, e.g. "W4", "L3", or "—".
    """
    completed = [g for g in games if g.get("gameState") == "OFF"]
    completed.sort(key=lambda g: g.get("gameDate", ""), reverse=True)

    streak_type: str | None = None
    streak_count = 0

    for g in completed:
        away = g.get("awayTeam", {})
        home = g.get("homeTeam", {})
        is_away = away.get("abbrev", "") == team_abbrev
        team_score = away.get("score", 0) if is_away else home.get("score", 0)
        opp_score = home.get("score", 0) if is_away else away.get("score", 0)

        result = "W" if team_score > opp_score else "L"

        if streak_type is None:
            streak_type = result
            streak_count = 1
        elif result == streak_type:
            streak_count += 1
        else:
            break

    return f"{streak_type}{streak_count}" if streak_type else "—"


def _build_team_streaks(team_abbrevs: list[str], ref_date: date | None = None) -> dict[str, str]:
    """Fetch each team's schedule and return computed streaks.

    Tries the full-season endpoint first (best accuracy across month
    boundaries). Falls back to current + previous month schedules if the
    season endpoint fails or returns no completed games, so a transient
    API error never leaves a team with "—".

    OT/SO losses are treated as regulation losses throughout.

    Args:
        team_abbrevs: List of three-letter team abbreviations.

    Returns:
        Dict mapping each abbreviation to a streak string like "W4" or "L3".
    """
    today = ref_date or local_today()
    if today.month == 1:
        prev_month = today.replace(year=today.year - 1, month=12, day=1).isoformat()
    else:
        prev_month = today.replace(month=today.month - 1, day=1).isoformat()

    streaks: dict[str, str] = {}
    for abbrev in team_abbrevs:
        streak = "—"
        try:
            games = fetch_team_season_schedule(abbrev)
            streak = _compute_streak_otl_as_loss(games, abbrev)
        except Exception as e:
            logger.warning(
                "Season schedule fetch failed for %s (%s) — trying monthly fallback", abbrev, e
            )

        if streak == "—":
            try:
                games = fetch_team_month_schedule(abbrev) + fetch_team_month_schedule(
                    abbrev, prev_month
                )
                streak = _compute_streak_otl_as_loss(games, abbrev)
                if streak != "—":
                    logger.info("Monthly fallback succeeded for %s: %s", abbrev, streak)
            except Exception as e:
                logger.warning("Monthly fallback also failed for %s: %s", abbrev, e)
                run_report.record("Some streak labels", run_report.NHL_UNAVAILABLE)

        streaks[abbrev] = streak
    return streaks


def our_conference(standings: list[dict]) -> tuple[str, list[str]]:
    """(conference abbrev, [our division, the other division]) from live standings.

    Falls back to the static team table when our team isn't in the standings.
    """
    me = next((t for t in standings if _safe_get(t, "teamAbbrev", "default") == TEAM_ABBREV), None)
    conf = (me or {}).get("conferenceAbbrev") or TEAM.conference
    our_div = (me or {}).get("divisionAbbrev") or TEAM.division
    divs = [our_div]
    for t in standings:
        d = t.get("divisionAbbrev", "")
        if t.get("conferenceAbbrev") == conf and d and d not in divs:
            divs.append(d)
    if len(divs) == 1:  # standings missing: use the static alignment
        divs += sorted({x.division for x in TEAMS.values() if x.conference == conf} - {our_div})
    return conf, divs


def _extract_conference_standings(
    standings: list[dict],
    team_streaks: dict[str, str] | None = None,
) -> dict:
    """Extract our conference's standings grouped by division.

    Keeps the teams in our conference, groups them by division (our division
    first), and sorts each division by the NHL's division rank (or points then
    regulation wins when the API omits it).

    Args:
        standings: Full list of team standing objects from the API.
        team_streaks: Optional pre-computed streak strings keyed by team
            abbreviation (OTL treated as L). When provided these replace the
            streak_code/streak_count values from the API.

    Returns:
        Dict keyed by division name (our division first, e.g. "Pacific" then
        "Central"), each a list of team dicts: abbrev, name, gp, wins, losses,
        ot_losses, points, point_pct, l10, streak, is_us, div_rank, wc_rank.
    """
    _, div_abbrevs = our_conference(standings)
    divisions: dict[str, list] = {DIVISION_NAMES.get(d, d): [] for d in div_abbrevs}

    for team in standings:
        div_name = DIVISION_NAMES.get(team.get("divisionAbbrev", ""))
        if div_name not in divisions:
            continue

        abbrev = _safe_get(team, "teamAbbrev", "default") or team.get("teamAbbrev", "")
        name = _safe_get(team, "teamCommonName", "default") or abbrev

        l10_w = team.get("l10Wins", 0)
        l10_l = team.get("l10Losses", 0)
        l10_otl = team.get("l10OtLosses", 0)
        l10 = f"{l10_w}-{l10_l}-{l10_otl}"

        streak = team_streaks.get(abbrev, "—") if team_streaks is not None else "—"

        divisions[div_name].append(
            {
                "abbrev": abbrev,
                "name": name,
                "gp": team.get("gamesPlayed", 0),
                "wins": team.get("wins", 0),
                "losses": team.get("losses", 0),
                "ot_losses": team.get("otLosses", 0),
                "points": team.get("points", 0),
                "point_pct": round(team.get("pointPctg", 0.0), 3),
                "l10": l10,
                "streak": streak,
                "is_us": abbrev == TEAM_ABBREV,
                # NHL-computed ranks (tiebreakers applied). 0/None when absent.
                "div_rank": team.get("divisionSequence") or 0,
                "wc_rank": team.get("wildcardSequence") or 0,
            }
        )

    for div_name in divisions:
        teams = divisions[div_name]
        if teams and all(t["div_rank"] for t in teams):
            teams.sort(key=lambda t: t["div_rank"])
        else:
            teams.sort(key=lambda t: (t["points"], t["wins"]), reverse=True)
            for i, t in enumerate(teams, 1):
                t["div_rank"] = i

    # Wild card order: everyone outside their division's top 3, ranked across the conference.
    others = [t for teams in divisions.values() for t in teams if t["div_rank"] > 3]
    if others and all(t["wc_rank"] for t in others):
        others.sort(key=lambda t: t["wc_rank"])
    else:
        others.sort(key=lambda t: (t["points"], t["wins"]), reverse=True)
    for i, t in enumerate(others, 1):
        t["wc_rank"] = i

    return divisions


def _extract_playoff_bracket(bracket_data: dict) -> dict | None:
    """Parse the raw playoff bracket API response into a clean structure.

    The NHL API returns a flat "series" list (not nested under "rounds").
    Wins are at the series level (topSeedWins/bottomSeedWins), not inside
    the team objects. Series without both teams known (TBD matchups) are
    included only for rounds that have at least one known matchup.

    Args:
        bracket_data: Raw response from the playoff-bracket endpoint.

    Returns:
        Dict with a "rounds" list, or None if the data is unusable.
    """
    if not bracket_data:
        return None

    raw_series = bracket_data.get("series", [])
    if not raw_series:
        return None

    # Group series by playoffRound
    rounds_map: dict[int, list] = {}
    for s in raw_series:
        round_num = s.get("playoffRound", 0)
        if round_num not in rounds_map:
            rounds_map[round_num] = []

        top = s.get("topSeedTeam") or {}
        bottom = s.get("bottomSeedTeam") or {}

        top_abbrev = top.get("abbrev", "TBD")
        bottom_abbrev = bottom.get("abbrev", "TBD")

        # Skip fully-TBD placeholder slots (future rounds not yet seeded)
        if top_abbrev == "TBD" and bottom_abbrev == "TBD":
            continue

        # Wins live at the series level, not inside the team objects
        top_wins = s.get("topSeedWins", 0)
        bottom_wins = s.get("bottomSeedWins", 0)

        winner_data = s.get("seriesWinner") or {}
        winner = winner_data.get("abbrev") or None

        involves_us = TEAM_ABBREV in (top_abbrev, bottom_abbrev)

        if winner:
            loser_wins = bottom_wins if winner == top_abbrev else top_wins
            series_status = f"{winner} wins 4\u2013{loser_wins}"
        elif top_wins == 0 and bottom_wins == 0:
            series_status = ""
        elif top_wins == bottom_wins:
            series_status = f"Series tied {top_wins}\u2013{bottom_wins}"
        elif top_wins > bottom_wins:
            series_status = f"{top_abbrev} leads {top_wins}\u2013{bottom_wins}"
        else:
            series_status = f"{bottom_abbrev} leads {bottom_wins}\u2013{top_wins}"

        rounds_map[round_num].append(
            {
                "letter": s.get("seriesLetter", ""),
                "top_seed": top_abbrev,
                "top_wins": top_wins,
                "bottom_seed": bottom_abbrev,
                "bottom_wins": bottom_wins,
                "winner": winner,
                "involves_us": involves_us,
                "series_status": series_status,
            }
        )

    if not rounds_map:
        return None

    rounds = [
        {
            "round": round_num,
            "name": ROUND_NAMES.get(round_num, f"Round {round_num}"),
            "series": series_list,
        }
        for round_num, series_list in sorted(rounds_map.items())
        if series_list  # only include rounds that have at least one known matchup
    ]

    return {"rounds": rounds} if rounds else None


def _extract_next_game_info(game: dict, ref_date: date | None = None) -> dict:
    """Build the next_game sub-dict from a raw game object.

    Args:
        game: Game object from the schedule API.

    Returns:
        Dict with date, opponent, home_or_away, weekday, is_today, days_until,
        plus start_time_utc, time (DISPLAY_TZ string) and venue when the API has them.
    """
    away_abbrev = _safe_get(game, "awayTeam", "abbrev", default="")
    home_abbrev = _safe_get(game, "homeTeam", "abbrev", default="")

    if away_abbrev == TEAM_ABBREV:
        home_or_away = "away"
        opponent = home_abbrev
    else:
        home_or_away = "home"
        opponent = away_abbrev

    info: dict = {
        "date": game.get("gameDate", "Unknown"),
        "opponent": opponent,
        "home_or_away": home_or_away,
    }
    game_date = _parse_date(info["date"])
    if game_date:
        today = ref_date or local_today()
        info["weekday"] = f"{game_date:%A}"
        info["is_today"] = game_date == today
        info["days_until"] = (game_date - today).days
    start_utc = game.get("startTimeUTC", "")
    if start_utc:
        info["start_time_utc"] = start_utc
        info["time"] = format_display_time(start_utc)
    venue = _safe_get(game, "venue", "default") or ""
    if venue:
        info["venue"] = venue
    return info


def _get_team_logo(standings: list[dict]) -> str:
    """Extract our team logo URL from the standings data.

    Args:
        standings: Full list of team standing objects from the API.

    Returns:
        Logo URL string, falling back to the known CDN URL if not found.
    """
    for team in standings:
        abbrev = _safe_get(team, "teamAbbrev", "default") or team.get("teamAbbrev", "")
        if abbrev == TEAM_ABBREV:
            logo = team.get("teamLogo", "")
            if logo:
                return logo
    return TEAM_LOGO_FALLBACK


# ---------------------------------------------------------------------------
# New data extractors (v3)
# ---------------------------------------------------------------------------


def _period_label(period_num: int, period_type: str) -> str:
    """Convert a period number and type into a display label like '1st' or 'OT'.

    Args:
        period_num: Period number (1, 2, 3, 4=OT, 5=SO).
        period_type: Period type string from the API ("REG", "OT", "SO").

    Returns:
        Human-readable period label.
    """
    if period_type in ("OT", "SO"):
        return period_type
    return {1: "1st", 2: "2nd", 3: "3rd"}.get(period_num, f"P{period_num}")


def goal_phase(time_in_period: str, period_label: str, period_type: str = "REG") -> str:
    """Where in a regulation period a goal came, in words.

    0:00-6:59 "early in the 2nd", 7:00-12:59 "midway through the 2nd",
    13:00 onward "late in the 2nd". Returns "" for overtime (a 5-minute
    period in the regular season) or an unparseable time.
    """
    if (period_type or "REG").upper() != "REG":
        return ""
    try:
        minutes = int(str(time_in_period).split(":")[0])
    except ValueError:
        return ""
    if minutes < 7:
        return f"early in the {period_label}"
    if minutes < 13:
        return f"midway through the {period_label}"
    return f"late in the {period_label}"


def _player_name_from_parts(obj: dict) -> str:
    """Extract a full player name from an API object with firstName/lastName dicts.

    Args:
        obj: Dict that may contain "firstName" and "lastName" fields (either
             plain strings or {"default": "..."} dicts).

    Returns:
        Full name string, or "Unknown" if unavailable.
    """
    first = _safe_get(obj, "firstName", "default") or obj.get("firstName", "")
    last = _safe_get(obj, "lastName", "default") or obj.get("lastName", "")
    if isinstance(first, str) and isinstance(last, str):
        return f"{first} {last}".strip() or "Unknown"
    return "Unknown"


def _full_player_name(obj: dict, name_lookup: dict[int, str] | None = None) -> str:
    """Best available full name for an API player object.

    Order: playerId lookup (full roster names) → firstName/lastName → abbreviated "name".
    """
    if name_lookup:
        full = name_lookup.get(obj.get("playerId"))
        if full:
            return full
    full = _player_name_from_parts(obj)
    return full if full != "Unknown" else _player_name(obj.get("name", ""))


def _extract_scoring_summary(landing: dict) -> list[dict]:
    """Parse the scoring summary from a gamecenter landing response.

    Args:
        landing: Raw response from the gamecenter landing endpoint.

    Returns:
        List of period dicts, each with "period", "period_label", and "goals".
        Goals contain time, team, scorer, assists, and strength ("EV"/"PP"/"SH").
    """
    periods = []
    for period in landing.get("summary", {}).get("scoring", []):
        pd = period.get("periodDescriptor", {})
        period_num = pd.get("number", 0)
        period_type = pd.get("periodType", "REG")
        label = _period_label(period_num, period_type)

        goals = []
        for g in period.get("goals", []):
            scorer = _player_name_from_parts(g)

            assists = []
            for a in g.get("assists", []):
                assist_name = _player_name_from_parts(a)
                if assist_name != "Unknown":
                    assists.append(assist_name)

            team_raw = g.get("teamAbbrev", "")
            team = (
                team_raw.get("default", "") if isinstance(team_raw, dict) else str(team_raw)
            ).strip()

            strength_raw = g.get("strength", "EV")
            if isinstance(strength_raw, dict):
                strength = strength_raw.get("code", "EV").upper()
            else:
                strength = str(strength_raw).upper() if strength_raw else "EV"
            # Normalize pen-shot → PS
            if strength in ("PEN-SHOT", "PENALTY-SHOT"):
                strength = "PS"

            goals.append(
                {
                    "time": g.get("timeInPeriod", ""),
                    "phase": goal_phase(g.get("timeInPeriod", ""), label, period_type),
                    "team": team,
                    "scorer": scorer,
                    "assists": assists,
                    "strength": strength,
                }
            )

        periods.append(
            {
                "period": period_num,
                "period_label": label,
                "goals": goals,
            }
        )

    return periods


def _extract_three_stars(landing: dict, name_lookup: dict[int, str] | None = None) -> list[dict]:
    """Parse the three stars from a gamecenter landing response.

    Args:
        landing: Raw response from the gamecenter landing endpoint.

    Returns:
        List of up to 3 star dicts: star number, name, team, position, summary.
    """
    stars = []
    for s in landing.get("summary", {}).get("threeStars", []):
        # name is {"default": "J. Roslovic"} — resolve to a full name via playerId when possible
        name = _full_player_name(s, name_lookup)

        team_raw = s.get("teamAbbrev", "")
        team = (
            team_raw.get("default", "") if isinstance(team_raw, dict) else str(team_raw)
        ).strip()

        summary = s.get("desc", "") or s.get("summary", "")
        if not summary:
            sv_pct = s.get("savePctg")
            gaa = s.get("goalsAgainstAverage")
            if s.get("position") == "G" and sv_pct is not None:
                # Goalies get save stats, not a skater line ("0G 0A 0PTS")
                summary = f"{sv_pct:.3f}".lstrip("0") + " SV%"
                if gaa is not None:
                    summary += f" · {gaa:.2f} GAA"
            else:
                summary = f"{s.get('goals', 0)}G {s.get('assists', 0)}A {s.get('points', 0)}PTS"

        stars.append(
            {
                "star": s.get("star", len(stars) + 1),
                "player_id": s.get("playerId"),
                "name": name,
                "team": team,
                "position": s.get("position", ""),
                "summary": summary,
            }
        )
    return stars[:3]


def goalie_game_line(saves: int, shots: int, shutout: bool) -> str:
    """'19 saves, shutout' or '22 of 23' — a goalie's game in words for the cards."""
    if shutout:
        return f"{saves} saves, shutout"
    return f"{saves} of {shots}"


def _apply_goalie_star_lines(stars: list[dict], last_game: dict) -> None:
    """Give goalie stars saves and shots for this game instead of a one-game GAA."""
    lines = last_game.get("goalie_lines") or {}
    for star in stars:
        if star.get("position") != "G":
            continue
        line = lines.get(star.get("player_id"))
        if not line:
            continue
        conceded = (
            last_game.get("opponent_score", 0)
            if star.get("team") == TEAM_ABBREV
            else last_game.get("our_score", 0)
        )
        shutout = conceded == 0 and line["saves"] == line["shots"]
        star["summary"] = goalie_game_line(line["saves"], line["shots"], shutout)


def _extract_season_series(games: list[dict], opponent: str) -> dict:
    """Build the head-to-head season series record vs a given opponent.

    Args:
        games: Full season schedule list from fetch_season_schedule().
        opponent: Opponent team abbreviation (e.g. "VGK").

    Returns:
        Dict with wins, losses, ot_losses, and a "label" like "2-1-0".
    """
    wins = losses = ot_losses = 0
    for g in games:
        if g.get("gameState") != "OFF":
            continue
        away = g.get("awayTeam", {})
        home = g.get("homeTeam", {})
        teams = {away.get("abbrev", ""), home.get("abbrev", "")}
        if TEAM_ABBREV not in teams or opponent not in teams:
            continue

        we_are_away = away.get("abbrev", "") == TEAM_ABBREV
        our_score = away.get("score", 0) if we_are_away else home.get("score", 0)
        opp_score = home.get("score", 0) if we_are_away else away.get("score", 0)
        period_type = _safe_get(g, "periodDescriptor", "periodType") or "REG"

        if our_score > opp_score:
            wins += 1
        elif period_type in ("OT", "SO"):
            ot_losses += 1
        else:
            losses += 1

    return {
        "wins": wins,
        "losses": losses,
        "ot_losses": ot_losses,
        "label": f"{wins}-{losses}-{ot_losses}",
    }


def _extract_upcoming_games(
    games: list[dict], n: int = 6, ref_date: date | None = None
) -> list[dict]:
    """Extract the next N upcoming our team games from a season schedule.

    Args:
        games: Full season schedule list from fetch_season_schedule().
        n: Number of upcoming games to return. The first is "Next Up"; the
            rest feed "Coming Up".

    Returns:
        List of game dicts from _extract_next_game_info().
    """
    upcoming = sorted(
        [g for g in games if g.get("gameState") in ("FUT", "PRE")],
        key=lambda g: (g.get("gameDate", ""), g.get("startTimeUTC", "")),
    )
    return [_extract_next_game_info(g, ref_date) for g in upcoming[:n]]


def _game_side(game: dict) -> str:
    """'away' or 'home' for our team in a raw schedule game."""
    return "away" if _safe_get(game, "awayTeam", "abbrev", default="") == TEAM_ABBREV else "home"


def _game_opponent(game: dict) -> str:
    away = _safe_get(game, "awayTeam", "abbrev", default="")
    home = _safe_get(game, "homeTeam", "abbrev", default="")
    return home if away == TEAM_ABBREV else away


def _extract_schedule_notes(
    upcoming: list[dict], season_games: list[dict] | None = None
) -> dict | None:
    """Summarise the current home/road run and the back-to-backs around it.

    The run is the stretch of games on the same side as the next game: the
    completed games that lead into it (from season_games) plus the upcoming
    games that continue it.

    Returns:
        Dict with run_type ("road"/"home"), played (completed games in the run,
        oldest first), run_games (upcoming games in the run), run_length
        (upcoming only), position (the next game's number in the run), total,
        run_reaches_end (the run covers every fetched upcoming game, so it may
        be longer), next_is_back_to_back (the next game is the day after the
        last completed game), last_played (that game), and back_to_backs
        (pairs of upcoming games on consecutive days); or None without games.
    """
    if not upcoming:
        return None
    first_side = upcoming[0].get("home_or_away")
    run = []
    for g in upcoming:
        if g.get("home_or_away") != first_side:
            break
        run.append({"opponent": g.get("opponent", ""), "date": g.get("date", "")})

    completed = sorted(
        (g for g in season_games or [] if g.get("gameState") in ("OFF", "FINAL")),
        key=lambda g: (g.get("gameDate", ""), g.get("startTimeUTC", "")),
        reverse=True,
    )
    played = []
    for g in completed:
        if _game_side(g) != first_side:
            break
        played.append({"opponent": _game_opponent(g), "date": g.get("gameDate", "")})
    played.reverse()

    last_played = None
    next_is_b2b = False
    if completed:
        last_played = {
            "opponent": _game_opponent(completed[0]),
            "date": completed[0].get("gameDate", ""),
            "home_or_away": _game_side(completed[0]),
        }
        d_last = _parse_date(last_played["date"])
        d_next = _parse_date(upcoming[0].get("date", ""))
        next_is_b2b = bool(d_last and d_next and (d_next - d_last).days == 1)

    back_to_backs = []
    for a, b in zip(upcoming, upcoming[1:], strict=False):
        da, db = _parse_date(a.get("date", "")), _parse_date(b.get("date", ""))
        if da and db and (db - da).days == 1:
            back_to_backs.append(
                [
                    {"opponent": a.get("opponent", ""), "date": a.get("date", "")},
                    {"opponent": b.get("opponent", ""), "date": b.get("date", "")},
                ]
            )

    return {
        "run_type": "road" if first_side == "away" else "home",
        "played": played,
        "run_length": len(run),
        "run_games": run,
        "position": len(played) + 1,
        "total": len(played) + len(run),
        "run_reaches_end": len(run) == len(upcoming),
        "next_is_back_to_back": next_is_b2b,
        "last_played": last_played,
        "back_to_backs": back_to_backs,
    }


def _game_period_type(game: dict) -> str:
    """REG, OT or SO for a completed schedule/boxscore game object."""
    pt = _safe_get(game, "gameOutcome", "lastPeriodType") or _safe_get(
        game, "periodDescriptor", "periodType"
    )
    pt = str(pt or "REG").upper()
    return pt if pt in ("REG", "OT", "SO") else "REG"


def _extract_last_meeting(
    games: list[dict],
    opponent: str,
    ref_date: date | None = None,
    exclude_game_id: int | None = None,
) -> dict | None:
    """Most recent completed game this season against `opponent`, in plain facts.

    exclude_game_id leaves out one game (the one being reported), so this also
    gives the previous meeting with the team just played. days_ago counts back
    from ref_date (the run's reference date).

    Returns:
        Dict with date, weekday, days_ago, our_score, opponent_score, result
        (W/L/OTL), period_type (REG/OT/SO) and location ("in Edmonton",
        "in Toronto", or "at <venue>" for a neutral site); None if no meeting yet.
    """
    meetings = []
    for g in games:
        if g.get("gameState") not in ("OFF", "FINAL"):
            continue
        away = _safe_get(g, "awayTeam", "abbrev", default="")
        home = _safe_get(g, "homeTeam", "abbrev", default="")
        if {away, home} == {TEAM_ABBREV, opponent} and g.get("id") != exclude_game_id:
            meetings.append(g)
    if not meetings:
        return None
    g = max(meetings, key=lambda x: (x.get("gameDate", ""), x.get("startTimeUTC", "")))

    away_is_us = _safe_get(g, "awayTeam", "abbrev", default="") == TEAM_ABBREV
    our_side, opp_side = ("awayTeam", "homeTeam") if away_is_us else ("homeTeam", "awayTeam")
    our_score = _safe_get(g, our_side, "score", default=0) or 0
    opp_score = _safe_get(g, opp_side, "score", default=0) or 0
    period_type = _game_period_type(g)
    if our_score > opp_score:
        result = "W"
    elif period_type in ("OT", "SO"):
        result = "OTL"
    else:
        result = "L"

    if g.get("neutralSite"):
        venue = _safe_get(g, "venue", "default") or ""
        location = f"at {venue}" if venue else ""
    else:
        place = _safe_get(g, "homeTeam", "placeName", "default") or ""
        location = f"in {place}" if place else ""

    meeting = {
        "date": g.get("gameDate", ""),
        "our_score": our_score,
        "opponent_score": opp_score,
        "result": result,
        "period_type": period_type,
        "home_or_away": "away" if away_is_us else "home",
    }
    if location:
        meeting["location"] = location
    game_date = _parse_date(meeting["date"])
    if game_date:
        meeting["weekday"] = f"{game_date:%A}"
        meeting["days_ago"] = ((ref_date or local_today()) - game_date).days
    return meeting


def _extract_recent_form(games: list[dict], n: int = 10) -> dict:
    """Extract our team's result in their last N completed games.

    Args:
        games: Full season schedule list from fetch_season_schedule().
        n: Number of recent completed games to include.

    Returns:
        Dict with "record" string (e.g. "6-3-1") and "games" list with
        per-game result, opponent, score, and date.
    """
    completed = sorted(
        [g for g in games if g.get("gameState") == "OFF"],
        key=lambda g: g.get("gameDate", ""),
        reverse=True,
    )
    recent = list(reversed(completed[:n]))  # chronological order

    wins = losses = ot_losses = 0
    form_games = []
    for g in recent:
        away = g.get("awayTeam", {})
        home = g.get("homeTeam", {})
        we_are_away = away.get("abbrev", "") == TEAM_ABBREV
        our_score = away.get("score", 0) if we_are_away else home.get("score", 0)
        opp_score = home.get("score", 0) if we_are_away else away.get("score", 0)
        opponent = home.get("abbrev", "") if we_are_away else away.get("abbrev", "")
        period_type = _safe_get(g, "periodDescriptor", "periodType") or "REG"

        if our_score > opp_score:
            game_result = "W"
            wins += 1
        elif period_type in ("OT", "SO"):
            game_result = "OTL"
            ot_losses += 1
        else:
            game_result = "L"
            losses += 1

        form_games.append(
            {
                "date": g.get("gameDate", ""),
                "opponent": opponent,
                "result": game_result,
                "score": f"{our_score}-{opp_score}",
            }
        )

    return {
        "record": f"{wins}-{losses}-{ot_losses}",
        "games": form_games,
    }


def _build_name_lookup(club_stats: dict) -> dict[str, str]:
    """Build a last-name → full-name lookup from club stats.

    Used to resolve abbreviated names (e.g. "C. Ingram" → "Connor Ingram")
    that the NHL API sometimes returns in boxscore/landing responses.

    Args:
        club_stats: Raw response from fetch_club_stats().

    Returns:
        Dict mapping lowercase last name to full name (e.g. {"ingram": "Connor Ingram"}).
    """
    lookup: dict[str, str] = {}
    for p in club_stats.get("skaters", []) + club_stats.get("goalies", []):
        full = _player_name_from_parts(p)
        if full != "Unknown":
            last = full.split()[-1].lower()
            lookup[last] = full
    return lookup


def _resolve_name(name: str, lookup: dict[str, str]) -> str:
    """Resolve an abbreviated name like "C. Ingram" to a full name using a lookup.

    If the name is already a full name (no trailing initial), returns it unchanged.

    Args:
        name: Player name string, possibly abbreviated.
        lookup: Last-name → full-name dict from _build_name_lookup().

    Returns:
        Resolved full name, or the original string if no match found.
    """
    parts = name.split()
    if len(parts) == 2 and parts[0].endswith("."):  # abbreviated: "C. Ingram"
        resolved = lookup.get(parts[1].lower())
        if resolved:
            return resolved
    return name


def _skater_name_from_stats(p: dict) -> str:
    """Extract a skater's name from a club-stats API player object.

    The club-stats endpoint may use firstName/lastName dicts or a nested
    name dict — this tries both forms.

    Args:
        p: Skater dict from the club-stats API response.

    Returns:
        Player name string.
    """
    full_name = _player_name_from_parts(p)
    if full_name != "Unknown":
        return full_name
    name_field = p.get("name", "")
    if name_field:
        return _player_name(name_field)
    return "Unknown"


def find_likely_starter(goalies: list[dict], headlines: list[str]) -> dict | None:
    """Return a top_goalie preview dict if a likely starter is found in headlines.

    Scans headlines for keywords indicating a confirmed or expected start
    (e.g. "starts", "starting", "in net") and matches goalie last names.
    Returns a formatted top_goalie dict (same shape as _extract_next_game_preview
    produces) so the caller can drop it directly into preview["top_goalie"].

    Args:
        goalies: List of goalie stat dicts from fetch_opponent_club_stats().
        headlines: News headlines to scan (from fetch_opponent_goalie_news()).

    Returns:
        Dict with name/games_played/wins/gaa/sv_pct, or None if no match.
    """
    start_keywords = {"start", "starts", "starting", "confirmed", "in net", "expected"}
    for headline in headlines:
        hl = headline.lower()
        if not any(kw in hl for kw in start_keywords):
            continue
        for g in goalies:
            last_name = _skater_name_from_stats(g).split()[-1].lower()
            if last_name in hl:
                gaa = g.get("goalsAgainstAvg") or g.get("goalsAgainstAverage") or 0.0
                return {
                    "name": _skater_name_from_stats(g),
                    "games_played": g.get("gamesPlayed", 0),
                    "wins": g.get("wins", 0),
                    "gaa": round(float(gaa), 2),
                    "sv_pct": round(_parse_save_pct(g), 3),
                }
    return None


def _extract_top_scorers(stats: dict, n: int = 5) -> list[dict]:
    """Extract the top N our skaters by points from club stats.

    Args:
        stats: Raw response from fetch_club_stats().
        n: Number of top scorers to return.

    Returns:
        List of player dicts: name, goals, assists, points, games_played, pp_goals.
    """
    skaters = sorted(
        stats.get("skaters", []),
        key=lambda p: (p.get("points", 0), p.get("goals", 0)),
        reverse=True,
    )
    result = []
    for p in skaters[:n]:
        result.append(
            {
                "name": _skater_name_from_stats(p),
                "goals": p.get("goals", 0),
                "assists": p.get("assists", 0),
                "points": p.get("points", 0),
                "games_played": p.get("gamesPlayed", 0),
                "pp_goals": p.get("powerPlayGoals", 0),
            }
        )
    return result


def fetch_player_game_log(player_id: int) -> list[dict]:
    """This season's game log for one player, newest game first."""
    return _get(f"{BASE_URL}/player/{player_id}/game-log/now").get("gameLog", [])


def _point_streak(game_log: list[dict]) -> tuple[int, bool]:
    """(consecutive games with a point, newest first; True if every game so far)."""
    streak = 0
    for g in game_log:
        if (g.get("points") or 0) > 0:
            streak += 1
        else:
            break
    return streak, bool(game_log) and streak == len(game_log)


def _extract_point_streaks(stats: dict, n: int = 5) -> list[dict]:
    """Current point streaks for the top-n our scorers.

    Returns:
        List of {name, games, from_season_start} for players with a streak of
        at least one game. Players whose game log can't be fetched are skipped.
    """
    skaters = sorted(
        stats.get("skaters", []),
        key=lambda p: (p.get("points", 0), p.get("goals", 0)),
        reverse=True,
    )[:n]
    streaks = []
    failed = 0
    for p in skaters:
        pid = p.get("playerId")
        if not pid:
            continue
        try:
            games, from_start = _point_streak(fetch_player_game_log(pid))
        except RuntimeError as e:
            logger.warning("Game log unavailable for player %s: %s", pid, e)
            failed += 1
            continue
        if games:
            streaks.append(
                {
                    "name": _skater_name_from_stats(p),
                    "games": games,
                    "from_season_start": from_start,
                }
            )
    if failed:
        run_report.record("Point streaks", run_report.NHL_UNAVAILABLE)
    return streaks


def _next_milestone(current: int) -> int:
    """Find the next round-number milestone above current.

    Milestones are multiples of 10 up to 100, then multiples of 50.

    Args:
        current: Current stat value.

    Returns:
        Next milestone integer.
    """
    if current < 100:
        return ((current // 10) + 1) * 10
    return ((current // 50) + 1) * 50


def _extract_milestones(stats: dict, threshold: int = 5) -> list[dict]:
    """Find our players within 'threshold' of a round-number milestone.

    Checks goals, assists, and points. Returns up to 5 entries sorted by
    how close the player is to their milestone (ascending).

    Args:
        stats: Raw response from fetch_club_stats().
        threshold: Maximum distance from a milestone to be included.

    Returns:
        List of milestone dicts: name, stat, current, next_milestone, needed.
    """
    results = []
    for p in stats.get("skaters", []):
        name = _skater_name_from_stats(p)
        for stat_key, stat_label in [
            ("goals", "goals"),
            ("assists", "assists"),
            ("points", "points"),
        ]:
            current = p.get(stat_key, 0)
            if current < 5:
                continue
            milestone = _next_milestone(current)
            needed = milestone - current
            if 1 <= needed <= threshold:
                results.append(
                    {
                        "name": name,
                        "stat": stat_label,
                        "current": current,
                        "next_milestone": milestone,
                        "needed": needed,
                    }
                )

    results.sort(key=lambda m: m["needed"])
    return results[:5]


def _extract_player_of_week(season_games: list[dict]) -> dict | None:
    """Find our team player with the most points across the last 5 games.

    Fetches boxscores for the 5 most recent completed games and aggregates
    individual player points. Returns None if data is unavailable.

    Args:
        season_games: Full season schedule list from fetch_season_schedule().

    Returns:
        Dict with name, goals, assists, points, games — or None.
    """
    completed = sorted(
        [g for g in season_games if g.get("gameState") == "OFF"],
        key=lambda g: g.get("gameDate", ""),
        reverse=True,
    )
    last_5 = completed[:5]
    if not last_5:
        return None

    # Keyed by playerId — boxscore names are abbreviated ("T. Jarry"), so the
    # winner's full name is resolved once at the end via the game roster.
    totals: dict[int | str, dict] = {}
    for g in last_5:
        game_id = g.get("id")
        if not game_id:
            continue
        try:
            boxscore = fetch_boxscore(game_id)
        except RuntimeError as e:
            logger.warning("Could not fetch boxscore %s for player-of-week: %s", game_id, e)
            continue

        away_abbrev = _safe_get(g, "awayTeam", "abbrev", default="")
        our_key = "awayTeam" if away_abbrev == TEAM_ABBREV else "homeTeam"
        our_player_stats = boxscore.get("playerByGameStats", {}).get(our_key, {})

        for skater in our_player_stats.get("forwards", []) + our_player_stats.get("defense", []):
            name = _full_player_name(skater)
            if name == "Unknown":
                continue
            key = skater.get("playerId") or name
            if key not in totals:
                totals[key] = {"name": name, "goals": 0, "assists": 0, "points": 0, "games": 0}
            totals[key]["goals"] += skater.get("goals", 0)
            totals[key]["assists"] += skater.get("assists", 0)
            totals[key]["points"] += skater.get("points", 0)
            totals[key]["games"] += 1
            totals[key]["last_game_id"] = game_id

    if not totals:
        return None

    best_key = max(totals, key=lambda k: (totals[k]["points"], totals[k]["goals"]))
    best = totals[best_key]
    best_name = best["name"]
    if isinstance(best_key, int):
        best_name = fetch_game_roster_names(best["last_game_id"]).get(best_key, best_name)
    return {
        "name": best_name,
        "goals": best["goals"],
        "assists": best["assists"],
        "points": best["points"],
        "games": best["games"],
    }


# Division rivals within this many points of us (inclusive) appear in the playoff race table
RACE_POINT_WINDOW = 10

# Only surface the magic number in the stretch run — earlier it's a meaningless ~100+.
MAGIC_NUMBER_MIN_GP = 62


def _calculate_magic_number(standings: list[dict]) -> int | None:
    """Calculate our magic number to clinch a playoff spot in our conference.

    The magic number is 1 + (max possible points for the 9th-place team in the
    conference) - (our current points). Returns 0 if already clinched, None if data is
    insufficient, we are below the bubble, or we have played fewer than
    MAGIC_NUMBER_MIN_GP games (too early in the season to be meaningful).

    Args:
        standings: Full list of team standing objects from the API.

    Returns:
        Magic number as an integer (0 = clinched), or None if unavailable.
    """
    conf_teams = []
    our_pts = None
    our_gp = 0
    conf, _ = our_conference(standings)

    for team in standings:
        if team.get("conferenceAbbrev", "") != conf:
            continue
        abbrev = _safe_get(team, "teamAbbrev", "default") or team.get("teamAbbrev", "")
        pts = team.get("points", 0)
        gp = team.get("gamesPlayed", 0)
        if abbrev == TEAM_ABBREV:
            our_pts = pts
            our_gp = gp
            # The NHL API sets clinchIndicator to "x" (division), "y" (wildcard),
            # or "z" (Presidents' Trophy) when a team has clinched a playoff spot.
            # Trust this directly rather than re-deriving it from point math.
            clinch = team.get("clinchIndicator", "")
            if clinch in ("x", "y", "z"):
                return 0
        conf_teams.append({"abbrev": abbrev, "points": pts, "gp": gp})

    if our_pts is None or len(conf_teams) < 9 or our_gp < MAGIC_NUMBER_MIN_GP:
        return None

    conf_teams.sort(key=lambda t: t["points"], reverse=True)
    ninth = conf_teams[8]  # 0-indexed; first team outside playoff picture
    ninth_max = ninth["points"] + 2 * (82 - ninth["gp"])
    magic = 1 + ninth_max - our_pts
    return max(0, magic)


def _extract_next_game_preview(
    next_game: dict,
    season_games: list[dict],
    standings_raw: list[dict],
    team_streaks: dict[str, str] | None = None,
    opp_stats: dict | None = None,
    ref_date: date | None = None,
) -> dict | None:
    """Build enriched preview data for the next our game.

    Uses the opponent's current-season stats (opp_stats, fetched by the caller;
    None leaves out the players to watch) to find their top forward,
    top defenseman, and most-used goalie. Also computes the season series
    record vs the next opponent and pulls their current streak from standings.

    Args:
        next_game: The next_game dict (opponent, date, home_or_away).
        season_games: Full season schedule from fetch_season_schedule().
        standings_raw: Raw standings list from fetch_standings().
        team_streaks: Optional pre-computed streak strings (OTL treated as L).

    Returns:
        Dict with season_series, opp_streak, opp_record, top_forward,
        top_defenseman, top_goalie — or None if opponent is unknown.
    """
    opponent = next_game.get("opponent")
    if not opponent:
        return None

    preview: dict = {}

    # Season series vs next opponent (reuse existing helper)
    preview["season_series"] = _extract_season_series(season_games, opponent)
    last_meeting = _extract_last_meeting(season_games, opponent, ref_date)
    if last_meeting:
        preview["last_meeting"] = last_meeting

    # Opponent streak + record from standings
    for team in standings_raw:
        abbrev = _safe_get(team, "teamAbbrev", "default") or team.get("teamAbbrev", "")
        if abbrev != opponent:
            continue
        preview["opp_streak"] = team_streaks.get(opponent, "—") if team_streaks is not None else "—"
        preview["opp_record"] = {
            "wins": team.get("wins", 0),
            "losses": team.get("losses", 0),
            "ot_losses": team.get("otLosses", 0),
            "points": team.get("points", 0),
        }
        break

    # Opponent's top players from club-stats
    if opp_stats is None:
        return preview
    try:
        skaters = opp_stats.get("skaters", [])
        goalies = opp_stats.get("goalies", [])

        forwards = sorted(
            [s for s in skaters if s.get("positionCode") in ("C", "L", "R")],
            key=lambda s: (s.get("points", 0), s.get("goals", 0)),
            reverse=True,
        )
        if forwards:
            f = forwards[0]
            preview["top_forward"] = {
                "name": _skater_name_from_stats(f),
                "position": f.get("positionCode", "F"),
                "goals": f.get("goals", 0),
                "assists": f.get("assists", 0),
                "points": f.get("points", 0),
                "games_played": f.get("gamesPlayed", 0),
            }

        defensemen = sorted(
            [s for s in skaters if s.get("positionCode") == "D"],
            key=lambda s: (s.get("points", 0), s.get("goals", 0)),
            reverse=True,
        )
        if defensemen:
            d = defensemen[0]
            preview["top_defenseman"] = {
                "name": _skater_name_from_stats(d),
                "goals": d.get("goals", 0),
                "assists": d.get("assists", 0),
                "points": d.get("points", 0),
                "games_played": d.get("gamesPlayed", 0),
            }

        active_goalies = sorted(
            [g for g in goalies if g.get("gamesPlayed", 0) > 0],
            key=lambda g: g.get("gamesPlayed", 0),
            reverse=True,
        )
        preview["all_goalies"] = active_goalies
        if active_goalies:
            g = active_goalies[0]
            sv = _parse_save_pct(g)
            gaa = g.get("goalsAgainstAvg") or g.get("goalsAgainstAverage") or 0.0
            preview["top_goalie"] = {
                "name": _skater_name_from_stats(g),
                "games_played": g.get("gamesPlayed", 0),
                "wins": g.get("wins", 0),
                "gaa": round(float(gaa), 2),
                "sv_pct": round(sv, 3),
            }
    except Exception as e:
        logger.warning("Could not read opponent stats for %s: %s", opponent, e)
        run_report.record("Players to watch", "NHL data incomplete")

    return preview


def _extract_playoff_race(standings_raw: list[dict], today_games: list[dict]) -> dict | None:
    """Extract playoff race context for our conference.

    NHL playoff seeding, per conference:
      - Top 3 in each of its two divisions earn automatic division spots (6 total).
      - The next 2 best records in the conference earn wild card spots.
    A team in a division spot (divisionSequence <= 3) is already in the playoffs and
    is NOT competing for a wild card — only a division rival overtaking them
    threatens their spot.

    Args:
        standings_raw: Full list of team standing objects from the API.
        today_games: List of today's games from fetch_today_schedule().

    Returns:
        Dict with our position/playoff status, bubble_teams list,
        key_games_tonight list, and a clinched flag. Returns None if
        our team's data is unavailable.
    """
    conf, divs = our_conference(standings_raw)
    our_div = divs[0]
    conf_teams = []
    division_teams = []
    for team in standings_raw:
        if team.get("conferenceAbbrev", "") != conf:
            continue
        abbrev = _safe_get(team, "teamAbbrev", "default") or team.get("teamAbbrev", "")
        pts = team.get("points", 0)
        gp = team.get("gamesPlayed", 0)
        div_rank = team.get("divisionSequence", 0)
        div_abbrev = team.get("divisionAbbrev", "")
        entry = {
            "abbrev": abbrev,
            "points": pts,
            "gp": gp,
            "games_remaining": 82 - gp,
            "div_rank": div_rank,
            "div_abbrev": div_abbrev,
            # None when the API omits it; 0 for division-spot holders
            "wc_rank": team.get("wildcardSequence"),
        }
        conf_teams.append(entry)
        if div_abbrev == our_div:
            division_teams.append(entry)

    if not conf_teams:
        return None

    conf_teams.sort(key=lambda t: (t["points"], -t["gp"]), reverse=True)
    division_teams.sort(key=lambda t: (t["points"], -t["gp"]), reverse=True)

    our_data = next((t for t in conf_teams if t["abbrev"] == TEAM_ABBREV), None)
    if our_data is None:
        return None

    our_div_rank = our_data["div_rank"]
    in_division_spot = our_div_rank <= 3  # top 3 in the division = automatic playoff berth

    our_conf_rank = next(
        (i + 1 for i, t in enumerate(conf_teams) if t["abbrev"] == TEAM_ABBREV), None
    )

    # Primary: trust the NHL API's own clinch indicator (x=division, y=wildcard, z=Presidents').
    our_raw = next(
        (
            t
            for t in standings_raw
            if (_safe_get(t, "teamAbbrev", "default") or t.get("teamAbbrev", "")) == TEAM_ABBREV
        ),
        None,
    )
    api_clinched = bool(our_raw and our_raw.get("clinchIndicator", "") in ("x", "y", "z"))

    # Fallback: 9th-place team's max possible points can't reach our total
    ninth = conf_teams[8] if len(conf_teams) >= 9 else None
    math_clinched = bool(
        ninth and (ninth["points"] + 2 * ninth["games_remaining"]) < our_data["points"]
    )

    clinched = api_clinched or math_clinched

    # Build tonight's opponent map
    tonight_map: dict[str, str] = {}
    tonight_venue: dict[str, str] = {}
    for game in today_games:
        away = _safe_get(game, "awayTeam", "abbrev") or ""
        home = _safe_get(game, "homeTeam", "abbrev") or ""
        if away and home:
            tonight_map[away] = home
            tonight_map[home] = away
            tonight_venue[away] = "away"
            tonight_venue[home] = "home"

    def _enrich(t: dict) -> dict:
        abbrev = t["abbrev"]
        return {
            "abbrev": abbrev,
            "points": t["points"],
            "gp": t["gp"],
            "games_remaining": t["games_remaining"],
            "max_possible_pts": t["points"] + 2 * t["games_remaining"],
            "div_rank": t["div_rank"],
            "division": DIVISION_NAMES.get(t["div_abbrev"], ""),
            "tonight_opponent": tonight_map.get(abbrev),
            "tonight_home_or_away": tonight_venue.get(abbrev),
        }

    if in_division_spot:
        # We hold a division spot. Show the division rivals close enough to
        # matter (within RACE_POINT_WINDOW points, above or below, inclusive)
        # plus the wild card race: the two wild-card holders and the first two
        # outside (wildcardSequence 1-4). Division-spot holders have
        # wildcardSequence 0, so they never land in the wild-card part.
        division_close = [
            t
            for t in division_teams
            if t["abbrev"] != TEAM_ABBREV
            and abs(t["points"] - our_data["points"]) <= RACE_POINT_WINDOW
        ]
        if all(t["wc_rank"] is not None for t in conf_teams):
            wild_card_race = sorted(
                (t for t in conf_teams if 1 <= t["wc_rank"] <= 4), key=lambda t: t["wc_rank"]
            )
        else:
            wild_card_race = conf_teams[6:10]  # API omitted wildcardSequence
        merged: list[dict] = []
        for t in division_close + wild_card_race:
            if t["abbrev"] != TEAM_ABBREV and t["abbrev"] not in {m["abbrev"] for m in merged}:
                merged.append(t)
        # Points desc; ties: our division first, then wild-card order
        merged.sort(
            key=lambda t: (
                -t["points"],
                0 if t["div_abbrev"] == our_div else 1,
                t["wc_rank"] if t["wc_rank"] is not None else 99,
            )
        )
        bubble_teams = [_enrich(t) for t in merged]
    else:
        # We need a wild card spot — show the conference wild card bubble (conf ranks 5–10)
        bubble_teams = [_enrich(t) for t in conf_teams[4:10] if t["abbrev"] != TEAM_ABBREV]

    # Key games tonight: relevant bubble/division games, excluding our own game
    relevant_abbrevs = {t["abbrev"] for t in bubble_teams}
    seen: set[tuple] = set()
    key_games: list[dict] = []
    for game in today_games:
        away = _safe_get(game, "awayTeam", "abbrev") or ""
        home = _safe_get(game, "homeTeam", "abbrev") or ""
        pair = tuple(sorted([away, home]))
        if pair in seen or TEAM_ABBREV in pair:
            continue
        seen.add(pair)
        if away in relevant_abbrevs or home in relevant_abbrevs:
            key_games.append({"away": away, "home": home})

    return {
        "our_points": our_data["points"],
        "our_gp": our_data["gp"],
        "our_games_remaining": our_data["games_remaining"],
        "our_rank": our_conf_rank,
        "our_div_rank": our_div_rank,
        "in_division_spot": in_division_spot,
        "bubble_teams": bubble_teams,
        "key_games_tonight": key_games,
        "clinched": clinched,
    }


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def get_team_data() -> dict:
    """Fetch all relevant our data and return as a structured dictionary.

    Fetches:
    - Most recently completed game (result, box score, team stats, all goalies,
      scoring summary, three stars, season series vs opponent, recap link)
    - our team standings summary + magic number
    - Full conference standings (regular season) OR playoff bracket
    - our logo URL
    - Next game + the five games after it (6 upcoming in total) and schedule notes
    - Recent form (last 10 games)
    - Top scorers leaderboard (season)
    - Milestone watch (players close to round numbers)
    - Player of the week (best performer over last 5 games)

    Returns:
        Dictionary with keys:
        last_game, standings, conference_standings, playoff_bracket,
        team_logo, next_game, upcoming_games, recent_form,
        top_scorers, milestones, player_of_week, magic_number.
    """
    result = {
        "last_game": None,
        "standings": None,
        "conference_standings": None,
        "playoff_bracket": None,
        "team_logo": TEAM_LOGO_FALLBACK,
        "next_game": None,
        "upcoming_games": [],
        "recent_form": None,
        "top_scorers": [],
        "milestones": [],
        "player_of_week": None,
        "magic_number": None,
        "playoff_race": None,
        "next_game_preview": None,
        "schedule_notes": None,
    }

    # --- Month schedule (more reliable for finding latest game) ---
    logger.info("Fetching current month schedule for %s", TEAM_ABBREV)
    current_month_games = fetch_month_schedule("now")

    # --- Last completed game ---
    last_game_raw = _find_last_completed_game(current_month_games)
    if last_game_raw is None:
        logger.info("No completed game this month, checking previous month")
        today = local_today()
        if today.month == 1:
            prev_month_date = today.replace(year=today.year - 1, month=12, day=1)
        else:
            prev_month_date = today.replace(month=today.month - 1, day=1)
        try:
            prev_month_games = fetch_month_schedule(prev_month_date.isoformat())
            last_game_raw = _find_last_completed_game(prev_month_games)
        except RuntimeError as e:
            logger.warning("Could not fetch previous month schedule: %s — skipping", e)

    # Final fallback: try week endpoints for recent dates when month endpoints fail
    if last_game_raw is None:
        logger.info("No completed game via month endpoints, trying week schedule fallback")
        today = local_today()
        for days_back in (3, 7, 10, 14):
            candidate = (today - timedelta(days=days_back)).isoformat()
            try:
                week_games = fetch_week_schedule(candidate)
                last_game_raw = _find_last_completed_game(week_games)
                if last_game_raw:
                    logger.info("Found last game via week fallback (%s)", candidate)
                    break
            except RuntimeError:
                pass

    # One reference date for every relative-day phrase in this run
    ref_date = reference_date(
        _parse_date(last_game_raw.get("gameDate", "")) if last_game_raw else None
    )
    result["reference_date"] = ref_date.isoformat()

    if last_game_raw:
        game_id = last_game_raw.get("id")
        logger.info("Fetching box score for game %s", game_id)
        boxscore = fetch_boxscore(game_id)
        name_lookup = fetch_game_roster_names(game_id)
        right_rail = fetch_right_rail(game_id)
        result["last_game"] = _extract_last_game_info(
            last_game_raw, boxscore, name_lookup, right_rail, ref_date
        )

        # Scoring summary + three stars from landing endpoint
        logger.info("Fetching landing data for game %s", game_id)
        try:
            landing = fetch_landing(game_id)
            scoring_summary = _extract_scoring_summary(landing)
            result["last_game"]["scoring_summary"] = scoring_summary
            result["last_game"]["game_winning_goal"] = _extract_game_winning_goal(
                result["last_game"]
            )

            # Build last-name → full-name lookup from scoring summary to resolve
            # abbreviated names (e.g. "M. Savoie") in three_stars, which the NHL
            # API only returns in abbreviated form.
            _full_name_lookup: dict[str, str] = {}
            for period in scoring_summary:
                for goal in period.get("goals", []):
                    for nm in [goal.get("scorer", "")] + goal.get("assists", []):
                        if nm and " " in nm and not nm.split()[0].endswith("."):
                            _full_name_lookup[nm.split()[-1].lower()] = nm

            three_stars = _extract_three_stars(landing, name_lookup)
            _apply_goalie_star_lines(three_stars, result["last_game"])
            for star in three_stars:
                parts = star["name"].split()
                if len(parts) >= 2 and parts[0].endswith("."):
                    resolved = _full_name_lookup.get(parts[-1].lower())
                    if resolved:
                        star["name"] = resolved
            result["last_game"]["three_stars"] = three_stars
            logger.info(
                "Scoring summary: %d periods; three stars: %d",
                len(result["last_game"]["scoring_summary"]),
                len(result["last_game"]["three_stars"]),
            )
        except RuntimeError as e:
            logger.warning("Could not fetch landing data: %s", e)
            run_report.record("Goal Log", run_report.NHL_UNAVAILABLE)
            run_report.record("Three Stars", run_report.NHL_UNAVAILABLE)
    else:
        logger.warning("No completed game found in the last two months")

    # --- Full season schedule: upcoming games, recent form, season series ---
    logger.info("Fetching full season schedule for %s", TEAM_ABBREV)
    season_games: list[dict] = []
    try:
        season_games = fetch_season_schedule()
        result["upcoming_games"] = _extract_upcoming_games(season_games, n=6, ref_date=ref_date)
        result["schedule_notes"] = _extract_schedule_notes(result["upcoming_games"], season_games)
        result["recent_form"] = _extract_recent_form(season_games, n=10)
        logger.info(
            "Upcoming: %d games; recent form: %s",
            len(result["upcoming_games"]),
            (result["recent_form"] or {}).get("record", "?"),
        )
        if result["upcoming_games"]:
            result["next_game"] = result["upcoming_games"][0]
        if result["last_game"]:
            opponent = result["last_game"]["opponent"]
            result["last_game"]["season_series"] = _extract_season_series(season_games, opponent)
            result["last_game"]["previous_meeting"] = _extract_last_meeting(
                season_games, opponent, ref_date, exclude_game_id=result["last_game"]["game_id"]
            )

        # Player of the week — fetch boxscores for last 5 games
        logger.info("Computing player of the week")
        result["player_of_week"] = _extract_player_of_week(season_games)
    except RuntimeError as e:
        logger.warning("Could not fetch season schedule: %s — falling back to week schedule", e)
        for section in ("Coming Up", "Recent form", "Player of the Week"):
            run_report.record(section, run_report.NHL_UNAVAILABLE)
        # Fall back to week schedule for next_game only
        current_week_games = fetch_week_schedule("now")
        next_game_raw = _find_next_game(current_week_games)
        if next_game_raw is None:
            today = ref_date
            days_until_monday = (7 - today.weekday()) % 7 or 7
            next_monday = today + timedelta(days=days_until_monday)
            next_week_games = fetch_week_schedule(next_monday.isoformat())
            next_game_raw = _find_next_game(next_week_games)
        if next_game_raw:
            result["next_game"] = _extract_next_game_info(next_game_raw, ref_date)
            result["upcoming_games"] = [result["next_game"]] if result["next_game"] else []

    # --- Standings ---
    logger.info("Fetching NHL standings")
    standings_raw = fetch_standings()

    # The calls the email depends on most go before the per-team streak
    # schedules (one request per team), so that if the API starts throttling,
    # streak labels are what degrades.
    next_opponent = (result.get("next_game") or {}).get("opponent", "")
    if not isinstance(next_opponent, str):
        next_opponent = ""

    # Playoff vs regular season: the bracket API is available as soon as the
    # NHL sets the bracket (before any playoff game), so it is a more reliable
    # signal than checking for gameType==3 in the current month's schedule.
    season_id = standings_raw[0].get("seasonId", 0) if standings_raw else 0
    bracket_raw = fetch_playoff_bracket(season_id) if season_id else None
    bracket_data = _extract_playoff_bracket(bracket_raw)
    is_playoffs = bool(bracket_data or _is_playoff_season(current_month_games))

    logger.info("Fetching club stats for %s", TEAM_ABBREV)
    club_stats: dict | None = None
    try:
        club_stats = fetch_club_stats()
    except RuntimeError as e:
        logger.warning("Could not fetch club stats: %s", e)
        for section in ("Top Scorers", "Milestones"):
            run_report.record(section, run_report.NHL_UNAVAILABLE)

    opp_stats: dict | None = None
    if next_opponent and result["next_game"] and season_games:
        try:
            opp_stats = fetch_opponent_club_stats(next_opponent)
        except RuntimeError as e:
            logger.warning("Could not fetch opponent stats for %s: %s", next_opponent, e)
            run_report.record("Players to watch", run_report.NHL_UNAVAILABLE)

    # The playoff race card waits until the stretch run; skip its data work until then.
    our_gp = next(
        (
            t.get("gamesPlayed", 0)
            for t in standings_raw
            if _safe_get(t, "teamAbbrev", "default") == TEAM_ABBREV
        ),
        0,
    )
    race_due = not is_playoffs and our_gp >= MAGIC_NUMBER_MIN_GP
    today_games: list[dict] = []
    if race_due:
        logger.info("Fetching today's league schedule for playoff race context")
        today_games = fetch_today_schedule(ref_date)

    # Build per-team streaks treating OTL as a regulation loss. Limit to
    # our conference's teams (the only ones displayed in the email) plus
    # the next opponent in case they're in the other conference.

    our_conf, _ = our_conference(standings_raw)
    all_abbrevs = []
    for t in standings_raw:
        # teamAbbrev is returned as {'default': 'EDM'} by the NHL API — use
        # _safe_get to unwrap the dict rather than testing isinstance(str).
        abbrev = _safe_get(t, "teamAbbrev", "default") or ""
        if abbrev:
            in_conference = t.get("conferenceAbbrev", "") == our_conf
            is_next_opponent = abbrev == next_opponent
            if in_conference or is_next_opponent:
                all_abbrevs.append(abbrev)

    all_abbrevs = list(set(all_abbrevs))  # Remove duplicates
    logger.info("Computing streaks (OTL=L) for %d teams", len(all_abbrevs))
    team_streaks = _build_team_streaks(all_abbrevs, ref_date)

    result["standings"] = _extract_standings_info(
        standings_raw, our_streak=team_streaks.get(TEAM_ABBREV, "—")
    )
    if result["standings"] is None:
        logger.warning("Could not find our team in standings data")

    result["division_gap"] = _extract_division_gap(standings_raw)
    result["team_logo"] = _get_team_logo(standings_raw)
    result["magic_number"] = _calculate_magic_number(standings_raw)
    logger.info("Magic number: %s", result["magic_number"])

    # --- Next game preview: H2H, opponent streak/record, top players ---
    if result["next_game"] and season_games:
        try:
            result["next_game_preview"] = _extract_next_game_preview(
                result["next_game"], season_games, standings_raw, team_streaks, opp_stats, ref_date
            )
            logger.info("Next game preview built for %s", result["next_game"].get("opponent", "?"))
        except Exception as e:
            logger.warning("Could not build next game preview: %s", e)

    # --- Playoff vs regular season ---
    if is_playoffs:
        logger.info(
            "Playoff season detected — bracket loaded: %s rounds",
            len((bracket_data or {}).get("rounds", [])),
        )
        result["playoff_bracket"] = bracket_data
    else:
        logger.info("Regular season — building conference standings")
        result["conference_standings"] = _extract_conference_standings(standings_raw, team_streaks)

        if not race_due:
            logger.info(
                "Playoff race skipped: we have played %d of the %d games it waits for",
                our_gp,
                MAGIC_NUMBER_MIN_GP,
            )
        else:
            try:
                result["playoff_race"] = _extract_playoff_race(standings_raw, today_games)
                clinched = (result["playoff_race"] or {}).get("clinched", False)
                logger.info(
                    "Playoff race: %s rank #%s, clinched=%s, key games tonight=%d",
                    TEAM_ABBREV,
                    (result["playoff_race"] or {}).get("our_rank", "?"),
                    clinched,
                    len((result["playoff_race"] or {}).get("key_games_tonight", [])),
                )
            except Exception as e:
                logger.warning("Could not build playoff race context: %s", e)
                run_report.record("Playoff Race", "could not build it")

    # --- Club stats: top scorers + milestones ---
    # In playoff mode, prefer playoff stats for the scorers table; fall back to
    # regular-season stats if no playoff games have been played yet (empty list).
    if club_stats is not None:
        result["club_stats"] = club_stats

        playoff_stats: dict = {}
        if result.get("playoff_bracket"):
            playoff_stats = fetch_club_stats_playoffs(season_id)
            logger.info("Playoff club stats: %d skaters", len(playoff_stats.get("skaters", [])))

        # Use playoff stats for scorers if they contain data (≥1 game played)
        if playoff_stats.get("skaters"):
            result["top_scorers"] = _extract_top_scorers(playoff_stats, n=5)
            result["playoff_scorers"] = True
        else:
            result["top_scorers"] = _extract_top_scorers(club_stats, n=5)
            result["playoff_scorers"] = False

        result["milestones"] = _extract_milestones(club_stats)
        if not result.get("playoff_scorers"):
            result["point_streaks"] = _extract_point_streaks(club_stats)
        logger.info(
            "Top scorers: %d; milestones: %d",
            len(result["top_scorers"]),
            len(result["milestones"]),
        )

        # Resolve any abbreviated player names (e.g. "C. Ingram" → "Connor Ingram")
        # using the full-name lookup built from club stats. This prevents the model from
        # hallucinating first names when the NHL API returns abbreviated forms.
        name_lookup = _build_name_lookup(club_stats)
        if result["last_game"]:
            lg = result["last_game"]
            for goalie in lg.get("goalies", []):
                goalie["name"] = _resolve_name(goalie["name"], name_lookup)
            if lg.get("goalie"):
                lg["goalie"]["name"] = _resolve_name(lg["goalie"]["name"], name_lookup)
            for skater in lg.get("top_skaters", []):
                skater["name"] = _resolve_name(skater["name"], name_lookup)
            for star in lg.get("three_stars", []):
                star["name"] = _resolve_name(star["name"], name_lookup)

    return result


# ---------------------------------------------------------------------------
# Player career context
# ---------------------------------------------------------------------------


def _build_career_snapshot(
    season_totals: list[dict],
    position: str,
    name: str,
    current_gp: int,
    current_goals: int,
    current_assists: int,
    current_points: int,
    current_sv_pct: float | None = None,
    current_gaa: float | None = None,
) -> dict:
    """Build a career trend snapshot for one player from their seasonTotals.

    Args:
        season_totals: List of season dicts from the player landing endpoint.
        position: Position code, e.g. "C", "LW", "D", "G".
        name: Player's display name.
        current_gp: Games played in the current season (from club stats).
        current_goals: Goals in the current season.
        current_assists: Assists in the current season.
        current_points: Points in the current season.
        current_sv_pct: Save percentage this season (goalies only).
        current_gaa: Goals against average this season (goalies only).

    Returns:
        Dict with career averages, current pace, trend direction, and season-by-season breakdown.
    """
    nhl_reg = [
        s for s in season_totals if s.get("gameTypeId") == 2 and s.get("leagueAbbrev") == "NHL"
    ]

    # Determine current season ID (max season in the data)
    if nhl_reg:
        current_season_id = max(s.get("season", 0) for s in nhl_reg)
    else:
        current_season_id = 0

    # Historical = all completed NHL regular seasons excluding the current one
    historical = [s for s in nhl_reg if s.get("season", 0) != current_season_id]

    # Aggregate by season (sum across teams if mid-season trade)
    season_map: dict[int, dict] = {}
    for s in historical:
        sid = s.get("season", 0)
        if sid not in season_map:
            season_map[sid] = {
                "season": sid,
                "gp": 0,
                "g": 0,
                "a": 0,
                "pts": 0,
                "wins": 0,
                "sv_pct_sum": 0.0,
                "gaa_sum": 0.0,
                "sv_pct_count": 0,
            }
        season_map[sid]["gp"] += s.get("gamesPlayed", 0)
        season_map[sid]["g"] += s.get("goals", 0)
        season_map[sid]["a"] += s.get("assists", 0)
        season_map[sid]["pts"] += s.get("points", 0)
        if position == "G":
            season_map[sid]["wins"] += s.get("wins", 0)
            sv = s.get("savePctg", 0.0)
            if sv:
                season_map[sid]["sv_pct_sum"] += sv
                season_map[sid]["sv_pct_count"] += 1
            season_map[sid]["gaa_sum"] += s.get("goalsAgainstAvg", 0.0)

    past_seasons = sorted(season_map.values(), key=lambda x: x["season"], reverse=True)[:3]
    seasons_sampled = len(past_seasons)

    def _season_label(sid: int) -> str:
        s = str(sid)
        return f"{s[:4]}-{s[4:6]}"

    if position == "G":
        season_by_season = []
        for s in past_seasons:
            sv_avg = s["sv_pct_sum"] / s["sv_pct_count"] if s["sv_pct_count"] else 0.0
            season_by_season.append(
                {
                    "season": _season_label(s["season"]),
                    "gp": s["gp"],
                    "wins": s["wins"],
                    "sv_pct": round(sv_avg, 3),
                    "gaa": round(s["gaa_sum"] / max(s["sv_pct_count"], 1), 2),
                }
            )

        if seasons_sampled >= 1 and current_sv_pct is not None:
            sv_values = [
                s["sv_pct_sum"] / s["sv_pct_count"] for s in past_seasons if s["sv_pct_count"]
            ]
            career_sv_avg = round(sum(sv_values) / len(sv_values), 3) if sv_values else 0.0
            delta = (current_sv_pct - career_sv_avg) if career_sv_avg else 0.0
            trend = "above" if delta > 0.005 else ("below" if delta < -0.005 else "on_pace")
            note = None
            if delta > 0.010:
                note = "career-best SV% pace"
            elif delta < -0.010:
                note = "below career SV% norm"
        else:
            career_sv_avg = None
            trend = "on_pace"
            delta = 0.0
            note = "limited career baseline" if seasons_sampled < 2 else None

        return {
            "name": name,
            "position": position,
            "seasons_sampled": seasons_sampled,
            "career_avg_sv_pct": career_sv_avg,
            "career_avg_gaa": None,
            "current_gp": current_gp,
            "current_sv_pct": current_sv_pct,
            "current_gaa": current_gaa,
            "trend": trend,
            "trend_delta": round(delta, 3),
            "season_by_season": season_by_season,
            "note": note,
        }

    # Skater path
    season_by_season = [
        {
            "season": _season_label(s["season"]),
            "gp": s["gp"],
            "g": s["g"],
            "a": s["a"],
            "pts": s["pts"],
        }
        for s in past_seasons
    ]

    if seasons_sampled >= 1:
        # Pace-normalise to per-82
        def _per82(val: int, gp: int) -> float:
            return round(val / gp * 82, 1) if gp else 0.0

        career_g82 = round(sum(_per82(s["g"], s["gp"]) for s in past_seasons) / seasons_sampled, 1)
        career_pts82 = round(
            sum(_per82(s["pts"], s["gp"]) for s in past_seasons) / seasons_sampled, 1
        )
        current_pts82 = _per82(current_points, current_gp) if current_gp else 0.0
        current_g82 = _per82(current_goals, current_gp) if current_gp else 0.0

        if career_pts82:
            trend_pct = round((current_pts82 - career_pts82) / career_pts82 * 100, 1)
            trend = "above" if trend_pct > 10 else ("below" if trend_pct < -10 else "on_pace")
        else:
            trend_pct = 0.0
            trend = "on_pace"

        note = None
        if trend_pct > 15:
            note = "career-best pace"
        elif trend_pct < -15:
            note = "below career norms"
    else:
        career_g82 = None
        career_pts82 = None
        current_pts82 = None
        current_g82 = None
        trend_pct = 0.0
        trend = "on_pace"
        note = "first NHL season — no career baseline"

    return {
        "name": name,
        "position": position,
        "seasons_sampled": seasons_sampled,
        "career_avg_goals_82": career_g82,
        "career_avg_points_82": career_pts82,
        "current_gp": current_gp,
        "current_goals": current_goals,
        "current_assists": current_assists,
        "current_points": current_points,
        "current_goals_82_pace": current_g82,
        "current_points_82_pace": current_pts82,
        "trend": trend,
        "trend_pct": trend_pct,
        "season_by_season": season_by_season,
        "note": note,
    }


def get_player_career_context(club_stats: dict) -> dict[str, dict]:
    """Fetch career history snapshots for key our players.

    Selects the top 5 forwards and top 2 defensemen by season points,
    plus the starting goalie by GP, then fetches each player's landing
    page to build a career trend snapshot.

    Args:
        club_stats: Raw response from fetch_club_stats().

    Returns:
        Dict mapping player name → career snapshot dict.
        Empty if club_stats is unavailable.
    """
    skaters = club_stats.get("skaters", [])
    goalies = club_stats.get("goalies", [])

    forwards = sorted(
        [p for p in skaters if p.get("positionCode") in ("C", "L", "R", "LW", "RW")],
        key=lambda p: (p.get("points", 0), p.get("goals", 0)),
        reverse=True,
    )[:5]

    defensemen = sorted(
        [p for p in skaters if p.get("positionCode") in ("D",)],
        key=lambda p: (p.get("points", 0), p.get("goals", 0)),
        reverse=True,
    )[:2]

    starters = sorted(
        goalies, key=lambda g: g.get("gamesStarted", g.get("gamesPlayed", 0)), reverse=True
    )[:1]

    key_players = forwards + defensemen + starters
    context: dict[str, dict] = {}

    for p in key_players:
        player_id = p.get("playerId")
        if not player_id:
            continue

        name = _skater_name_from_stats(p)
        position = p.get("positionCode", "")
        gp = p.get("gamesPlayed", 0)

        try:
            landing = fetch_prospect_landing(player_id)
            season_totals = landing.get("seasonTotals", [])

            if position == "G":
                sv_pct = p.get("savePctg") or p.get("savePercentage")
                gaa = p.get("goalsAgainstAverage") or p.get("goalsAgainstAvg")
                snapshot = _build_career_snapshot(
                    season_totals=season_totals,
                    position=position,
                    name=name,
                    current_gp=gp,
                    current_goals=0,
                    current_assists=0,
                    current_points=0,
                    current_sv_pct=round(float(sv_pct), 3) if sv_pct else None,
                    current_gaa=round(float(gaa), 2) if gaa else None,
                )
            else:
                snapshot = _build_career_snapshot(
                    season_totals=season_totals,
                    position=position,
                    name=name,
                    current_gp=gp,
                    current_goals=p.get("goals", 0),
                    current_assists=p.get("assists", 0),
                    current_points=p.get("points", 0),
                )

            context[name] = snapshot
            logger.info(
                "Career snapshot: %s — trend=%s (%s seasons sampled)",
                name,
                snapshot.get("trend"),
                snapshot.get("seasons_sampled"),
            )
        except Exception as e:
            logger.warning("Could not fetch career context for %s (id=%s): %s", name, player_id, e)

    return context
