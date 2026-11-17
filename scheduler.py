"""Daily scheduler for the NHL Daily digest.

For production, GitHub Actions runs the pipeline on a fixed UTC schedule
(see `.github/workflows/digest.yml`). This module's
`start_scheduler()` is for long-running **local** runs: the `schedule`
library fires at `RUN_TIME` in the machine's local timezone.

The pipeline fetches NHL data, generates a briefing, and sends the email.
Errors in the scheduled run are caught and logged so the loop keeps going.
"""

import json
import logging
import os
import time
from datetime import UTC, datetime

import schedule

import run_report
from config import SETTINGS
from digest import (
    enable_preview,
    generate_digest,
    generate_fine_print,
    generate_on_this_day,
    generate_playoff_race_analysis,
    generate_subject,
    generate_what_we_learned,
)
from emailer import _get_preheader, render_email, send_email, send_recap_email
from game_log import append_game, format_for_prompt, goalie_starts, load_game_log
from moneypuck import fetch_team_advanced_stats
from news import fetch_opponent_goalie_news, fetch_team_headlines
from nhl import (
    NHL_TEAM_NAMES,
    TEAM_ABBREV,
    fetch_club_stats,
    fetch_team_injuries,
    find_likely_starter,
    get_player_career_context,
    get_prospects_data,
    get_team_data,
    latest_completed_game,
)
from weather import fetch_game_weather

logger = logging.getLogger(__name__)


def _log_timestamp() -> str:
    """UTC wall-clock time for log lines only (never for email content)."""
    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")


# Local wall-clock time for `start_scheduler()` (HH:MM). Not used by GitHub Actions.
RUN_TIME = "05:00"

# Output folder for `python main.py --preview` (git-ignored).
PREVIEW_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "preview")


def _write_preview(subject: str, briefing: str, data: dict) -> None:
    """Preview mode: write the email that would have been sent, plus the run report."""
    html, text = render_email(subject, briefing, data)
    os.makedirs(PREVIEW_DIR, exist_ok=True)
    files = {
        "digest.html": html,
        "digest.txt": text,
        "subject.txt": subject + "\n",
        "preheader.txt": _get_preheader(data) + "\n",
        "report.json": json.dumps(data.get("missing_data", []), indent=2) + "\n",
    }
    for name, content in files.items():
        with open(os.path.join(PREVIEW_DIR, name), "w", encoding="utf-8") as f:
            f.write(content)
    logger.info("Preview written to %s (%d bytes of HTML)", PREVIEW_DIR, len(html.encode()))


# Chip colour per score (white text on each is at least 5:1)
SUFFER_COLORS = {
    1: "#2e7d32",
    2: "#2e7d32",
    3: "#4f7a28",
    4: "#5b6b1f",
    5: "#6d6a00",
    6: "#8a5a00",
    7: "#a34700",
    8: "#b3360b",
    9: "#c62828",
    10: "#9c1c1c",
}


def _lead_swings(last_game: dict) -> tuple[int, int, bool]:
    """(our biggest lead, biggest deficit, lost a 2+ goal lead) from the goal log."""
    ours = opp = 0
    max_lead = max_deficit = 0
    lost_two_goal_lead = False
    had_two_goal_lead = False
    for period in last_game.get("scoring_summary", []):
        if period.get("period_label") == "SO":
            continue
        for goal in period.get("goals", []):
            if goal.get("team") == TEAM_ABBREV:
                ours += 1
            else:
                opp += 1
            diff = ours - opp
            max_lead = max(max_lead, diff)
            max_deficit = max(max_deficit, -diff)
            if diff >= 2:
                had_two_goal_lead = True
            elif had_two_goal_lead and diff <= 0:
                lost_two_goal_lead = True
    return max_lead, max_deficit, lost_two_goal_lead


def _streak_after(recent_form: dict | None) -> tuple[str, int]:
    """("W"/"L", length) of the run the reported game ends; OT/SO losses count as losses."""
    games = (recent_form or {}).get("games") or []
    if not games:
        return "", 0
    kind = "W" if games[-1].get("result") == "W" else "L"
    n = 0
    for g in reversed(games):
        if ("W" if g.get("result") == "W" else "L") != kind:
            break
        n += 1
    return kind, n


def _calculate_suffer_score(last_game: dict, recent_form: dict | None = None) -> dict:
    """Calculate the Suffer-O-Meter score from the last game result.

    Base: regulation win 2, OT/SO win 4, OT/SO loss 6, regulation loss 8.
    Wins: shutout -1, won by 3+ -1, one-goal regulation win +1, came back
    from 2+ down -1. Any result: led by 2+ and lost the lead +2. Losses:
    lost by 3+ +1. Streak after the game (from recent_form, which ends with
    the reported game): 3+ wins -1, 3+ losses +1. Clamped to 1-10.

    Args:
        last_game: The last_game dict from nhl.get_team_data().
        recent_form: data["recent_form"], for the streak the game extends.

    Returns:
        Dict with score (1-10), label, color (chip background) and reasons
        (short phrases for what moved the score).
    """
    result = last_game.get("result", "")
    won = result == "W"
    our_score = last_game.get("our_score", 0)
    opp_score = last_game.get("opponent_score", 0)
    margin = abs(our_score - opp_score)
    period_type = (last_game.get("period_type") or "REG").upper()
    extra_time = period_type in ("OT", "SO")
    ending = "shootout" if period_type == "SO" else "overtime"

    reasons: list[str] = []
    if won:
        score = 4 if extra_time else 2
        if extra_time:
            reasons.append(f"{ending} win")
    else:
        score = 6 if extra_time else 8
        if extra_time:
            reasons.append(f"{ending} loss")

    _, max_deficit, lost_lead = _lead_swings(last_game)
    if won:
        if not extra_time and margin == 1:
            score += 1
            reasons.append("one-goal win")
        if margin >= 3:
            score -= 1
            reasons.append("won by 3 or more")
        if opp_score == 0:
            score -= 1
            reasons.append("shutout")
        if max_deficit >= 2:
            score -= 1
            reasons.append(f"came back from {max_deficit} down")
    if lost_lead:
        score += 2
        reasons.append("blew a 2-goal lead")
    if not won and margin >= 3:
        score += 1
        reasons.append("lost by 3 or more")

    kind, n = _streak_after(recent_form)
    if kind == "W" and n >= 3:
        score -= 1
        reasons.append(f"{n} straight wins")
    elif kind == "L" and n >= 3:
        score += 1
        reasons.append(f"{n} straight losses")

    score = max(1, min(10, score))

    if score <= 2:
        label = "Peak happiness. Enjoy it, it won't last."
    elif score <= 4:
        label = "Good vibes. Cautiously optimistic."
    elif score <= 6:
        label = "A win, but it hurt. It always hurts." if won else "A point is a point. Allegedly."
    elif score <= 8:
        label = "The boys tried. Sort of."
    else:
        label = "Staring into the void. The void stares back."
    return {"score": score, "label": label, "color": SUFFER_COLORS[score], "reasons": reasons}


def _has_unsent_game(game_log: list[dict]) -> bool:
    """True if a recently completed game exists that isn't in the game log yet.

    Defaults to True if the schedule API is unreachable, so a game isn't missed.
    """
    try:
        game = latest_completed_game()
    except RuntimeError as e:
        logger.warning("Could not check recent schedule: %s — defaulting to send", e)
        return True
    if game is None:
        logger.info("No completed game in the last few days")
        return False
    already_sent = any(
        g.get("date") == game["date"] and g.get("opponent") == game["opponent"] for g in game_log
    )
    logger.info(
        "Latest completed game: %s vs %s — %s",
        game["date"],
        game["opponent"],
        "already sent" if already_sent else "not yet sent",
    )
    return not already_sent


def run_pipeline(force: bool = False, preview: bool = False) -> bool:
    """Execute the full NHL Daily pipeline: fetch, generate, send.

    First checks for a recently completed game that hasn't been sent
    yet (i.e. isn't in the game log). If there isn't one, the pipeline is
    skipped. This makes the job safe to run several times a day at any hour:
    the first run after a game sends it, later runs skip.

    Args:
        force: If True, bypass the unsent-game check and always run.
        preview: If True (implies force), write the email to PREVIEW_DIR instead
            of sending it, never touch game_log.json,
            and record every model prompt (stubbed without ANTHROPIC_API_KEY).

    Returns:
        True if a digest was sent (or previewed), False if the run was skipped.

    Errors are raised so callers can catch and log them appropriately.
    """
    if preview:
        force = True
        enable_preview(os.path.join(PREVIEW_DIR, "prompts"))
    logger.info("Pipeline starting%s", " (preview)" if preview else " (forced)" if force else "")

    game_log = load_game_log()

    if not force and not _has_unsent_game(game_log):
        timestamp = _log_timestamp()
        logger.info("No unsent game — digest skipped at %s", timestamp)
        return False

    run_report.reset()
    data = get_team_data()

    # Inject season game log so the model has historical context
    data["game_log"] = format_for_prompt(game_log)
    data["goalie_starts"] = goalie_starts(game_log, data.get("last_game"))

    # Inject current news headlines to inform the model's writing
    logger.info("Fetching %s news headlines", TEAM_ABBREV)
    data["news_headlines"] = fetch_team_headlines()
    data["injuries"] = fetch_team_injuries()

    last_game = data.get("last_game")
    if not last_game:
        timestamp = _log_timestamp()
        logger.info("No game data found — digest skipped at %s", timestamp)
        return False

    data["suffer_score"] = _calculate_suffer_score(last_game, data.get("recent_form"))

    # Advanced stats (MoneyPuck)
    logger.info("Fetching MoneyPuck advanced stats")
    data["advanced_stats"] = fetch_team_advanced_stats()
    if not data["advanced_stats"]:
        run_report.record("Season 5v5", "MoneyPuck data unavailable")

    # Road game weather + likely starter detection
    next_game = data.get("next_game")
    if next_game:
        logger.info(
            "Fetching game weather for %s (%s)",
            next_game.get("opponent", ""),
            next_game.get("home_or_away", ""),
        )
        data["road_weather"] = fetch_game_weather(
            next_game.get("opponent", ""),
            next_game.get("home_or_away", "away"),
        )

        # Silently swap the displayed goalie if news confirms a likely starter
        # (named next_preview: `preview` is the run_pipeline flag)
        next_preview = data.get("next_game_preview")
        if next_preview:
            team_name = NHL_TEAM_NAMES.get(next_game.get("opponent", ""), "")
            if team_name:
                opp_headlines = fetch_opponent_goalie_news(team_name)
                likely = find_likely_starter(next_preview.get("all_goalies", []), opp_headlines)
                if likely:
                    next_preview["top_goalie"] = likely
                    logger.info("Goalie override: %s", likely["name"])
    else:
        data["road_weather"] = None

    logger.info("Fetching prospects data")
    data["prospects"] = [] if "prospects" in SETTINGS.hide_cards else get_prospects_data()

    logger.info("Fetching player career context")
    try:
        club = data.get("club_stats") or fetch_club_stats()
        data["player_context"] = get_player_career_context(club)
    except Exception as e:
        logger.warning("Player career context unavailable: %s", e)
        data["player_context"] = {}
        run_report.record("Player career notes", run_report.NHL_UNAVAILABLE)

    briefing = generate_digest(data)

    hidden = SETTINGS.hide_cards  # skip the work (and model calls) for hidden cards
    data["what_we_learned"] = (
        [] if "what_we_learned" in hidden else generate_what_we_learned(data, briefing)
    )

    ref = data.get("reference_date")
    data["on_this_day"] = (
        None
        if "on_this_day" in hidden
        else generate_on_this_day(datetime.fromisoformat(ref).date() if ref else None)
    )
    data["playoff_race_analysis"] = (
        "" if "playoff_race" in hidden else generate_playoff_race_analysis(data)
    )
    data["fine_print"] = generate_fine_print(data)

    data["missing_data"] = run_report.entries()
    if data["missing_data"]:
        logger.warning(
            "Missing-data report: %s",
            "; ".join(f"{e['section']} ({e['reason']})" for e in data["missing_data"]),
        )

    subject = generate_subject(data)
    if preview:
        _write_preview(subject, briefing, data)
        return True
    send_email(subject, briefing, data)

    # Persist this game to the rolling log (pass already-loaded games to avoid re-reading file)
    append_game(last_game, games=game_log)

    timestamp = _log_timestamp()
    logger.info("Digest sent at %s", timestamp)
    return True


def run_recap_pipeline() -> None:
    """Execute the season recap pipeline: generate AI analysis and send recap email.

    Calls season_recap.py to generate content with the configured model (with web
    search on Anthropic), then sends the recap email via Resend and marks the
    sentinel so it isn't re-sent.
    """
    from season_recap import (
        _mark_recap_sent,
        _season_label,
        generate_good_bad_middling,
        generate_offseason_priorities,
        generate_player_grades,
        generate_recap_subject,
        generate_season_overview,
    )

    logger.info("Season recap pipeline starting")
    data = get_team_data()
    game_log = load_game_log()
    data["game_log"] = format_for_prompt(game_log)

    recap_data = {
        "overview": generate_season_overview(data),
        "good_bad_middling": generate_good_bad_middling(data),
        "player_grades": generate_player_grades(data),
        "offseason_priorities": generate_offseason_priorities(data),
        "last_game": data.get("last_game"),
        "top_scorers": data.get("top_scorers", []),
        "standings": data.get("standings"),
        "playoff_bracket": data.get("playoff_bracket"),
    }

    subject = generate_recap_subject(data, recap_data)
    send_recap_email(subject, recap_data)
    _mark_recap_sent(_season_label(game_log))
    logger.info("Season recap email sent")


def start_scheduler() -> None:
    """Start the blocking daily scheduler loop.

    Schedules run_pipeline() to run every day at RUN_TIME (local wall clock).
    Wraps each run in a try/except so a failure does not kill the loop.

    Blocks indefinitely — run this as a background process or service.
    """

    def _safe_run():
        """Wrapper that catches and logs any pipeline error."""
        try:
            run_pipeline()
        except Exception as exc:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            logger.error("Pipeline failed at %s: %s", timestamp, exc, exc_info=True)

    schedule.every().day.at(RUN_TIME).do(_safe_run)
    logger.info("Scheduler started — the digest will run every day at %s", RUN_TIME)

    while True:
        schedule.run_pending()
        time.sleep(30)  # check every 30 seconds
