"""Season recap email pipeline for NHL Daily.

Detects when the team's season has ended and sends a single comprehensive
recap email exactly RECAP_DELAY_DAYS later. Uses the configured model; on Anthropic
it also gets the web search tool so it can find expert analysis, cap figures and
offseason rumours from credible hockey sources rather than relying on training
knowledge.
"""

import json
import logging
import os
import re as _re
from datetime import UTC, date, datetime, timedelta

from dotenv import load_dotenv

import llm
from config import SETTINGS
from emailer.theme import ABBR, NAME, NEWSLETTER, NICK
from game_log import load_game_log
from nhl import fetch_month_schedule

load_dotenv()

logger = logging.getLogger(__name__)

RECAP_DELAY_DAYS = 7
SENTINEL_PATH = os.path.join(os.path.dirname(__file__), "season_recap_sent.json")

_RECAP_SYSTEM = (
    f"You are a senior NHL analyst and beat writer who has covered the {NAME} "
    "for over a decade. You write sharp, honest, deeply informed analysis — not fan content. "
    + (
        "You have access to web search and should use it freely to find: current expert "
        "analysis, season statistical breakdowns, salary cap figures, contract statuses "
        "(UFA/RFA), and offseason rumours from credible hockey sources (The Athletic, "
        "Sportsnet, NHL.com, PuckPedia, Hockey Reference, Daily Faceoff). "
        if SETTINGS.llm.provider == "anthropic"
        else "You do not have web search: work only from the season data provided, and do "
        "not state contract, cap or rumour details that the data does not contain. "
    )
    + "Be specific and data-driven. Name players, cite stats, reference real situations. "
    "Do not hedge or add disclaimers. Write as if this is going in a premium newsletter.\n\n"
    "CRITICAL: Never open with meta-commentary about your research, process, or what you are "
    "about to write. No phrases like 'The research is comprehensive', 'Here is the overview', "
    "'Based on my research', 'Let me analyze', or any similar preamble. "
    "Begin immediately with the substantive content itself."
)


# ---------------------------------------------------------------------------
# Season-end detection
# ---------------------------------------------------------------------------


def _season_label(game_log: list) -> str:
    """Derive a season label like '2024-25' from the most recent game date."""
    if not game_log:
        return "unknown"
    last_date_str = game_log[-1].get("date", "")
    try:
        dt = datetime.strptime(last_date_str, "%Y-%m-%d")
        # NHL season crosses two calendar years; month < 7 means second year of season
        if dt.month < 7:
            return f"{dt.year - 1}-{str(dt.year)[2:]}"
        return f"{dt.year}-{str(dt.year + 1)[2:]}"
    except (ValueError, TypeError):
        return "unknown"


def _last_game_date(game_log: list) -> date | None:
    """Return the date of the most recently logged game, or None."""
    if not game_log:
        return None
    last_date_str = game_log[-1].get("date", "")
    try:
        return datetime.strptime(last_date_str, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def _has_upcoming_games(within_days: int = 21) -> bool:
    """Return True if we have any games scheduled in the next N days."""
    today = datetime.now(UTC).date()
    cutoff = today + timedelta(days=within_days)
    today_str = today.isoformat()
    cutoff_str = cutoff.isoformat()

    months_to_check = [today_str]
    # Also check next month if the cutoff window crosses a month boundary
    next_month_start = (today.replace(day=28) + timedelta(days=4)).replace(day=1)
    if next_month_start <= cutoff:
        months_to_check.append(next_month_start.isoformat())

    for month_str in months_to_check:
        try:
            games = fetch_month_schedule(month_str)
            for g in games:
                game_date = g.get("gameDate", "")
                state = g.get("gameState", "")
                if today_str <= game_date <= cutoff_str and state in ("PRE", "FUT", "LIVE"):
                    logger.info("Upcoming game found on %s (state=%s)", game_date, state)
                    return True
        except Exception as e:
            logger.warning("Could not check upcoming schedule for %s: %s", month_str, e)

    return False


def _recap_already_sent(season_label: str) -> bool:
    """Return True if the recap for this season has already been sent."""
    try:
        with open(SENTINEL_PATH, encoding="utf-8") as f:
            data = json.load(f)
        return data.get("season") == season_label
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return False


def _mark_recap_sent(season_label: str) -> None:
    """Write the sentinel file marking this season's recap as sent."""
    today = datetime.now(UTC).date().isoformat()
    try:
        with open(SENTINEL_PATH, "w", encoding="utf-8") as f:
            json.dump({"season": season_label, "sent_date": today}, f, indent=2)
        logger.info("Marked recap as sent for season %s on %s", season_label, today)
    except OSError as e:
        logger.warning("Could not write recap sentinel: %s", e)


def should_send_recap() -> bool:
    """Return True iff today is the correct day to send the season recap.

    All three conditions must hold:
    1. The last logged game was exactly RECAP_DELAY_DAYS ago.
    2. We have no games scheduled in the next 21 days (season truly over).
    3. The recap has not already been sent this season.
    """
    game_log = load_game_log()
    last_date = _last_game_date(game_log)
    if not last_date:
        logger.info("Recap check: no game log entries — skipping")
        return False

    today = datetime.now(UTC).date()
    days_since = (today - last_date).days

    if days_since != RECAP_DELAY_DAYS:
        logger.info(
            "Recap check: last game was %d day(s) ago (need exactly %d) — skipping",
            days_since,
            RECAP_DELAY_DAYS,
        )
        return False

    if _has_upcoming_games():
        logger.info(f"Recap check: {NICK} have upcoming games — not end of season")
        return False

    season = _season_label(game_log)
    if _recap_already_sent(season):
        logger.info("Recap check: recap already sent for %s — skipping", season)
        return False

    logger.info("Recap check: all conditions met for %s — recap due today", season)
    return True


# ---------------------------------------------------------------------------
# Model calls (web search only on Anthropic, see llm.py)
# ---------------------------------------------------------------------------


def _call_with_search(system: str, prompt: str, max_tokens: int = 4000) -> str:
    """Ask the configured model, letting it search the web when the provider can.

    Only Anthropic runs web search (llm.py); other providers answer from the
    season data in the prompt. Returns "" on failure.
    """
    try:
        return llm.complete(system, prompt, max_tokens, web_search=True).text
    except llm.LLMError as e:
        logger.error("Recap call failed: %s", e)
        return ""


def _call_standard(system: str, prompt: str, max_tokens: int = 2000) -> str:
    """Ask the configured model without tools — used for JSON-structured outputs."""
    try:
        return llm.complete(system, prompt, max_tokens).text
    except llm.LLMError as e:
        logger.error("Recap call failed: %s", e)
        return ""


# ---------------------------------------------------------------------------
# Season context builder
# ---------------------------------------------------------------------------


def _build_season_context(data: dict) -> str:
    """Build a compact text block describing the season for model prompts."""
    lines: list[str] = []

    standings = data.get("standings") or {}
    bracket = data.get("playoff_bracket")
    last_game = data.get("last_game") or {}

    if bracket:
        # Find the final series involving our team
        for round_dict in reversed(bracket.get("rounds", [])):
            for s in round_dict.get("series", []):
                if s.get("involves_us"):
                    status = s.get("series_status", "")
                    round_name = round_dict.get("name", "")
                    lines.append(f"SEASON RESULT: Playoffs — {status} ({round_name})")
                    break
            else:
                continue
            break
    else:
        w = standings.get("wins", "?")
        losses = standings.get("losses", "?")
        otl = standings.get("ot_losses", "?")
        record = f"{w}–{losses}–{otl}"
        lines.append(f"SEASON RESULT: Did not qualify for playoffs. Final record: {record}")

    if last_game:
        opp = last_game.get("opponent", "")
        result = last_game.get("result", "")
        es = last_game.get("our_score", 0)
        os_ = last_game.get("opponent_score", 0)
        lines.append(f"FINAL GAME: {ABBR} {es}–{os_} {opp} ({result})")

    scorers = data.get("top_scorers", [])
    if scorers:
        lines.append("\nSEASON TOP SCORERS:")
        for p in scorers[:8]:
            lines.append(
                f"  {p['name']}: {p.get('goals', 0)}G {p.get('assists', 0)}A "
                f"{p.get('points', 0)}PTS"
            )

    game_log_text = data.get("game_log", "")
    if game_log_text:
        lines.append(f"\n{game_log_text}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_json_list(raw: str, label: str) -> list | None:
    """Extract a JSON array from a model response that may contain citations.

    Strips web-search citation markers that would break JSON parsing, then
    locates the outermost [ ] boundaries and parses. Returns None on failure.
    """
    text = raw.strip()
    # Strip citation markers injected by web search tool
    text = _re.sub(r"【\d+†[^】]*】", "", text)
    text = _re.sub(r"\[\d+\]", "", text)
    # Strip markdown code fences
    text = _re.sub(r"```(?:json)?", "", text)
    start = text.find("[")
    end = text.rfind("]") + 1
    if start == -1 or end <= start:
        logger.warning("%s: no JSON array found in response:\n%s", label, raw[:500])
        return None
    try:
        result = json.loads(text[start:end])
        if isinstance(result, list):
            return result
        logger.warning("%s: parsed JSON is not a list", label)
    except (json.JSONDecodeError, ValueError) as e:
        snippet = text[start : start + 300]
        logger.warning("%s: JSON parse error: %s\nraw snippet: %s", label, e, snippet)
    return None


# ---------------------------------------------------------------------------
# Content generators
# ---------------------------------------------------------------------------


def generate_season_overview(data: dict) -> str:
    """Generate a 3–4 paragraph honest season narrative.

    Args:
        data: Full team data dict from get_team_data() with game_log injected.

    Returns:
        Prose string, or "" on error.
    """
    context = _build_season_context(data)
    prompt = (
        f"{context}\n\n"
        f"Search for expert retrospectives on the {NAME}' season, then write "
        "exactly 4 paragraphs as a season overview. Cover: regular-season trajectory, "
        "key turning points, how far they went in the playoffs and why, and the defining "
        "narrative arc. Be honest about both the highs and the failures. "
        "Plain prose only — no headers, no bullet points, no list. Exactly 4 paragraphs. "
        "Start directly with the first sentence — no preamble."
    )
    logger.info("Generating season overview")
    return _call_with_search(_RECAP_SYSTEM, prompt, max_tokens=900)


def generate_good_bad_middling(data: dict) -> dict:
    """Generate The Good / The Bad / The Middling analysis sections.

    Args:
        data: Full team data dict.

    Returns:
        Dict with string keys 'good', 'bad', 'middling'.
    """
    context = _build_season_context(data)
    prompt = (
        f"{context}\n\n"
        f"Search for expert analysis and season grades for the {NICK}, then assess "
        "the season under three headings. Each section should have 3–4 specific "
        "observations with player names, stats, and real situations — not generalities.\n\n"
        "Each observation must start with a short bold title on its own line using "
        "**Title Here** format, followed by a paragraph of 2–4 sentences. "
        "Example of one observation:\n\n"
        "**McDavid's Historic Pace**\n"
        "McDavid posted 123 points in 78 games and carried stretches where the supporting"
        " cast disappeared.\n\n"
        "Return your answer in exactly this format (include the section headers verbatim):\n\n"
        "THE GOOD\n"
        "[3-4 titled observations]\n\n"
        "THE BAD\n"
        "[3-4 titled observations]\n\n"
        "THE MIDDLING\n"
        "[3-4 titled observations]"
    )
    logger.info("Generating good/bad/middling")
    raw = _call_with_search(_RECAP_SYSTEM, prompt, max_tokens=2500)

    result = {"good": "", "bad": "", "middling": ""}
    current: str | None = None
    buffer: list[str] = []

    for line in raw.splitlines():
        stripped = line.strip().upper().rstrip(":")
        if stripped == "THE GOOD":
            if current and buffer:
                result[current] = "\n".join(buffer).strip()
            current, buffer = "good", []
        elif stripped == "THE BAD":
            if current and buffer:
                result[current] = "\n".join(buffer).strip()
            current, buffer = "bad", []
        elif stripped == "THE MIDDLING":
            if current and buffer:
                result[current] = "\n".join(buffer).strip()
            current, buffer = "middling", []
        elif current is not None:
            buffer.append(line)

    if current and buffer:
        result[current] = "\n".join(buffer).strip()

    return result


def generate_player_grades(data: dict) -> list[dict]:
    """Grade 8–10 key players for the season.

    Args:
        data: Full team data dict.

    Returns:
        List of dicts with keys: name, position, grade, reasoning.
        Falls back to a single raw-text entry if JSON parsing fails.
    """
    context = _build_season_context(data)
    json_schema = (
        '[{"name": "...", "position": "C/LW/D/G", "grade": "A", '
        '"reasoning": "one concise sentence"}, ...]'
    )
    # Step 1: gather analysis with web search
    research_prompt = (
        f"{context}\n\n"
        f"Search for season stats and expert player grades for the {NAME}, "
        "then write a brief analysis of 8–10 key players — grade each one "
        "(A+, A, A–, B+, B, B–, C+, C, C–, D, F) and explain why in one sentence. "
        "Include McDavid, Draisaitl, the starting goalie, top defenceman, and key role players."
    )
    logger.info("Generating player grades (research pass)")
    research = _call_with_search(_RECAP_SYSTEM, research_prompt, max_tokens=1200)

    # Step 2: convert to clean JSON with no-tools call
    format_prompt = (
        f"Convert this player analysis into a JSON array. "
        f"Output ONLY the raw JSON array — no markdown, no text before or after, no citations:\n"
        f"{json_schema}\n\nAnalysis to convert:\n{research}"
    )
    logger.info("Generating player grades (JSON format pass)")
    raw = _call_standard(_RECAP_SYSTEM, format_prompt, max_tokens=1200)
    grades = _extract_json_list(raw, "player_grades")
    if grades:
        return grades
    # Last resort: try parsing the research text directly
    grades = _extract_json_list(research, "player_grades_research")
    return grades or []


def generate_offseason_priorities(data: dict) -> list[dict]:
    """Generate 5–7 actionable offseason priorities.

    Args:
        data: Full team data dict.

    Returns:
        List of dicts with keys: priority, label, detail.
        label is one of: Critical, Important, Monitor.
    """
    context = _build_season_context(data)
    json_schema = (
        '[{"priority": "short title (5–7 words)", "label": "Critical", '
        '"detail": "2–3 sentences of specific explanation"}, ...]'
    )
    # Step 1: gather research with web search
    research_prompt = (
        f"{context}\n\n"
        f"Search for current {NAME} cap figures, UFA/RFA contract statuses, "
        "positional needs, coaching situations, and offseason rumours. "
        "Then write out 5–7 offseason priorities. Each must be specific — "
        "name real players, real cap numbers, real situations. "
        "Classify each as Critical, Important, or Monitor based on urgency."
    )
    logger.info("Generating offseason priorities (research pass)")
    research = _call_with_search(_RECAP_SYSTEM, research_prompt, max_tokens=1800)

    # Step 2: convert to clean JSON with no-tools call
    format_prompt = (
        f"Convert this offseason priorities analysis into a JSON array. "
        f"Output ONLY the raw JSON array — no markdown, no text before or after, no citations:\n"
        f"{json_schema}\n\nAnalysis to convert:\n{research}"
    )
    logger.info("Generating offseason priorities (JSON format pass)")
    raw = _call_standard(_RECAP_SYSTEM, format_prompt, max_tokens=1800)
    priorities = _extract_json_list(raw, "offseason_priorities")
    if priorities:
        return priorities
    priorities = _extract_json_list(research, "offseason_priorities_research")
    return priorities or []


def generate_recap_subject(data: dict, recap_data: dict) -> str:
    """Generate a short, punchy subject line for the recap email.

    Args:
        data: Full team data dict.
        recap_data: Dict containing the generated recap content sections.

    Returns:
        Subject line string.
    """
    context = _build_season_context(data)
    overview_snippet = (recap_data.get("overview") or "")[:300]
    prompt = (
        f"{context}\n\nSeason overview excerpt: {overview_snippet}\n\n"
        "Write one short, punchy email subject line for the end-of-season recap email. "
        "Under 60 characters. Capture the season's essence — honest, not promotional. "
        "Return ONLY the subject line text, nothing else."
    )
    try:
        text = llm.complete(_RECAP_SYSTEM, prompt, 60).text.strip().strip("\"'")
        return text or f"{NEWSLETTER} — Season Recap"
    except Exception as e:
        logger.warning("Recap subject generation failed: %s", e)
        game_log = load_game_log()
        return f"{NEWSLETTER} — {_season_label(game_log)} Season Recap"
