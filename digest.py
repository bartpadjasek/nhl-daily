"""Model-written content for the NHL Daily digest (any provider, see llm.py).

Takes structured NHL data and produces a punchy 200-250 word briefing
written in the voice of a knowledgeable, witty NHL analyst.
"""

import logging
import os
import re
from datetime import date, datetime
from types import SimpleNamespace

import requests
from dotenv import load_dotenv

import llm
import run_report
from config import SETTINGS, TEAM
from nhl import MAGIC_NUMBER_MIN_GP, division_gap_text, local_now, past_day_phrase
from team import CONFERENCE_NAMES, DIVISION_NAMES

load_dotenv()

# Team words used in prompts and KEY FACTS (config.toml [team])
NAME = TEAM.name  # "Edmonton Oilers"
NICK = TEAM.nickname  # "Oilers"
PLACE = TEAM.place  # "Edmonton"
ABBR = TEAM.abbrev  # "EDM"
DIV = DIVISION_NAMES[TEAM.division]  # "Pacific"
CONF = CONFERENCE_NAMES[TEAM.conference]  # "Western"

MODEL_ID = SETTINGS.llm.model  # config.toml [llm] model (or the provider default)

NAME_RULES = (
    "CRITICAL — names and teams: every player in the data is tagged with a team abbreviation; "
    f"only players tagged {ABBR} play for the {NICK}. Never describe an opponent's player as "
    f"one of the {NICK} or credit their goals to {PLACE}. Use names exactly as given; if a first name is only an "
    "initial (e.g. 'T. Jarry'), keep the initial or use the surname alone — never guess or "
    "expand it to a full first name."
)

SYSTEM_PROMPT = (
    f"You are an NHL beat reporter specialising in the {NAME}. "
    f"You know every player on every NHL roster — not just the {NICK} — by name, position, and role. "
    f"You cover the {NICK} daily and write exclusively for {NICK} fans: engaged, knowledgeable, not casual. "
    f"Write like a disciplined hockey journalist who is genuinely invested in the {NICK}' "
    "success but not a fanboy: honest about problems, measured in praise. "
    "Frame everything through what it means for the standings, the playoff race, and the "
    "team's larger trajectory — readers care about positioning and what's at stake. "
    "Use dry, observational wit: humor emerges from the situation, not from forced quips. "
    "Reference the team's history and current-season momentum to give weight to each result. "
    "Be direct, use hockey language, don't pad it out. "
    "CRITICAL — factual accuracy: only reference a player's position or role if it appears "
    "in the data provided. Never infer positions or roles from your training knowledge. "
    "Never self-correct a name mid-sentence. Use only the names provided in the data. "
    "CRITICAL — injured/unavailable players: if a player appears in the PLAYER AVAILABILITY "
    "section, they did not play. Never describe their in-game performance, say they "
    "'weren't a factor', or imply they were on the ice. Either omit them or note they were absent. "
    "CRITICAL — time and place: never calculate elapsed time or infer where a game was played. "
    "Use only the relative dates and venues given in KEY FACTS; if a time relation is not "
    "provided, do not state one. " + NAME_RULES
)

logger = logging.getLogger(__name__)


def _format_long_date(dt: datetime) -> str:
    """Format as 'April 4, 2026' without platform-specific strftime (e.g. %-d)."""
    return f"{dt.strftime('%B')} {dt.day}, {dt.year}"


def _local_now() -> datetime:
    """Now in LOCAL_TZ (config local time zone), from the shared clock nhl.local_now."""
    return local_now()


def _reference_day(data: dict) -> datetime:
    """The run's reference date (nhl.reference_date) as a datetime; today if absent."""
    ref = data.get("reference_date")
    if ref:
        try:
            return datetime.fromisoformat(str(ref)[:10])
        except ValueError:
            pass
    return _local_now()


def _ending_words(period_type: str | None) -> str:
    return {"OT": "in overtime", "SO": "in a shootout"}.get(
        (period_type or "REG").upper(), "in regulation"
    )


def _result_words(result: str, our_score: int, opp_score: int, period_type: str | None) -> str:
    """e.g. "won 3-2 in overtime", "lost 2-7 in regulation" (our score first)."""
    verb = "won" if result == "W" else "lost"
    return f"{verb} {our_score}-{opp_score} {_ending_words(period_type)}"


def _where_words(home_or_away: str, opponent: str) -> str:
    return f"home vs {opponent}" if home_or_away == "home" else f"away at {opponent}"


def _short_date(date_str: str) -> str:
    """'2026-11-14' → 'Nov 14'."""
    try:
        d = datetime.fromisoformat(date_str[:10])
    except ValueError:
        return date_str
    return f"{d:%b} {d.day}"


def _last_game_when(last_game: dict) -> str:
    """'last night', 'earlier today', or 'on Wednesday, November 11 (3 days ago)'."""
    return past_day_phrase(
        last_game.get("days_ago"), last_game.get("weekday", ""), last_game.get("date_label", "")
    )


def _next_game_when(next_game: dict) -> str:
    """'tonight, Saturday, November 14', 'tomorrow, Sunday, November 15', or
    'Tuesday, November 17 (in 3 days)'."""
    try:
        d = datetime.fromisoformat(next_game.get("date", "")[:10])
        label = f"{d:%A}, {d:%B} {d.day}"
    except ValueError:
        label = next_game.get("date", "")
    days = next_game.get("days_until")
    if days == 0:
        return f"tonight, {label}"
    if days == 1:
        return f"tomorrow, {label}"
    if days is None:
        return label
    return f"{label} (in {days} days)"


def _plural(n: int, word: str, plural: str | None = None) -> str:
    return f"{n} {word if n == 1 else plural or word + 's'}"


def _relative_game_day(next_game: dict) -> str:
    """'tonight', 'tomorrow' or 'on Tuesday, November 17' for the next game."""
    days = next_game.get("days_until")
    if days == 0:
        return "tonight"
    if days == 1:
        return "tomorrow"
    when = _next_game_when(next_game)
    return f"on {when.split(' (in ')[0]}"


def _schedule_note_text(notes: dict | None, next_game: dict | None = None) -> str:
    """Plain-words position in the current road trip or homestand, e.g.
    'road trip, game 2 of 6 tonight (TOR played; then PHI Nov 15, FLA Nov 17, ...)'."""
    if not notes or not notes.get("run_games"):
        return ""
    road = notes.get("run_type") == "road"
    played = notes.get("played") or []
    total = notes.get("total") or notes.get("run_length", 0)
    position = notes.get("position") or len(played) + 1
    upcoming = ", ".join(f"{g['opponent']} {_short_date(g['date'])}" for g in notes["run_games"])
    when = _relative_game_day(next_game) if next_game else ""

    if total <= 1:
        where = "on the road" if road else "at home"
        return f"next game is {where} ({upcoming}); the one after is not"

    kind = "road trip" if road else "homestand"
    at_least = "at least " if notes.get("run_reaches_end") else ""
    text = f"{kind}, game {position} of {at_least}{total}"
    if when:
        text += f" {when}"
    if played:
        done = ", ".join(g["opponent"] for g in played)
        text += f" ({done} played; then {upcoming})"
    else:
        text += f" (starts with {upcoming})"
    return text


def _back_to_back_text(notes: dict | None, next_game: dict | None) -> str:
    """'tonight at PHI is the second game in two nights; CAR and STL are also on
    consecutive days' — or "" when there is no back-to-back."""
    if not notes:
        return ""
    parts = []
    if notes.get("next_is_back_to_back") and next_game:
        at = "at" if next_game.get("home_or_away") == "away" else "vs"
        parts.append(
            f"{_relative_game_day(next_game)} {at} {next_game.get('opponent', '')} "
            "is the second game in two nights"
        )
    also = "also " if parts else ""
    for a, b in notes.get("back_to_backs", []):
        parts.append(f"{a['opponent']} and {b['opponent']} are {also}on consecutive days")
    return "; ".join(parts)


def _series_words(ss: dict | None) -> str:
    """'Oilers 1 win, 1 loss' (team nickname first) (adds overtime/shootout losses when there are any)."""
    if not ss:
        return ""
    parts = [_plural(ss.get("wins", 0), "win"), _plural(ss.get("losses", 0), "loss", "losses")]
    if ss.get("ot_losses"):
        parts.append(
            _plural(ss["ot_losses"], "overtime or shootout loss", "overtime or shootout losses")
        )
    return f"{NICK} " + ", ".join(parts)


def _goalie_starts_lines(starts: dict | None) -> list[str]:
    """Order of recent starts plus each goalie's last three, from the game log."""
    if not starts or not starts.get("order"):
        return []
    order = ", ".join(
        f"{_short_date(o['date'])} {o['name'].split()[-1] if o['name'] else '?'}"
        for o in starts["order"]
    )
    lines = [f"{ABBR} goalie starts, newest first: {order}"]
    for g in starts.get("by_goalie", []):
        games = []
        for st in g["starts"]:
            at = "at" if st.get("home_or_away") == "away" else "vs"
            games.append(
                f"{_short_date(st['date'])} {at} {st['opponent']} {st['result']} "
                f"{st['our_score']}-{st['opponent_score']} ({st['saves']} of {st['shots']} saves)"
            )
        label = "start" if len(games) == 1 else f"{len(games)} starts"
        lines.append(f"{g['name']} last {label}: " + "; ".join(games))
    return lines


def _point_streak_lines(streaks: list[dict] | None, min_games: int = 5) -> list[str]:
    items = []
    for p in streaks or []:
        if p.get("games", 0) >= min_games:
            tail = " (every game this season)" if p.get("from_season_start") else ""
            items.append(f"{p['name']} {p['games']} games{tail}")
    return [f"Point streaks: {'; '.join(items)}"] if items else []


def _shutout_line(last_game: dict) -> str:
    """'Shutout: Devon Levi, 19 saves' — or the opponent's shutout of our team."""
    so = last_game.get("shutout")
    if so and so.get("goalies"):
        who = " and ".join(so["goalies"])
        combined = " (combined)" if len(so["goalies"]) > 1 else ""
        return f"Shutout{combined}: {who}, {so['saves']} saves"
    if last_game.get("our_score", 0) == 0:
        opp = last_game.get("opponent_goalie") or {}
        if opp.get("name"):
            return (
                f"Shut out: {NICK} blanked by {opp['name']} ({last_game.get('opponent', '')}), "
                f"{opp.get('saves', 0)} saves"
            )
    return ""


def _game_winning_goal_text(last_game: dict) -> str:
    if last_game.get("decided_in_shootout"):
        return "decided in a shootout (no game-winning goal in play)"
    gwg = last_game.get("game_winning_goal")
    if not gwg:
        return ""
    assists = gwg.get("assists") or []
    helpers = f"assisted by {' and '.join(assists)}" if assists else "unassisted"
    strength = f", {gwg['strength']}" if gwg.get("strength", "EV") not in ("EV", "") else ""
    phase = f" ({gwg['phase']})" if gwg.get("phase") else ""
    return (
        f"{gwg['scorer']} ({gwg['team']}), {gwg['period_label']} {gwg['time']}{phase}{strength}, "
        f"{helpers}"
    )


def _last_meeting_text(
    meeting: dict | None, opponent: str, label_prefix: str = "Last meeting"
) -> str:
    if not meeting:
        return ""
    try:
        d = datetime.fromisoformat(meeting["date"][:10])
        label = f"{d:%A}, {d:%B} {d.day}"
    except (KeyError, ValueError):
        label = meeting.get("date", "")
    ago = f" ({meeting['days_ago']} days ago)" if meeting.get("days_ago") is not None else ""
    where = f", {meeting['location']}" if meeting.get("location") else ""
    result = _result_words(
        meeting.get("result", ""),
        meeting.get("our_score", 0),
        meeting.get("opponent_score", 0),
        meeting.get("period_type"),
    )
    return f"{label_prefix} with {opponent}: {label}{ago}{where}, {result}"


def _key_facts_lines(data: dict) -> list[str]:
    """Facts computed in code (dates, venues, how the game ended) for every prompt."""
    now = _reference_day(data)
    lines = [f"Today: {now:%A}, {_format_long_date(now)}"]

    last_game = data.get("last_game")
    if last_game:
        opp = last_game.get("opponent", "")
        result = _result_words(
            last_game.get("result", ""),
            last_game.get("our_score", 0),
            last_game.get("opponent_score", 0),
            last_game.get("period_type"),
        )
        when = _last_game_when(last_game)
        when = when[3:] if when.startswith("on ") else when
        lines.append(
            f"Last game: {when}, {_where_words(last_game.get('home_or_away', ''), opp)}, {result}"
        )
        shutout = _shutout_line(last_game)
        if shutout:
            lines.append(shutout)
        gwg = _game_winning_goal_text(last_game)
        if gwg:
            lines.append(f"Game-winning goal: {gwg}")
        previous = _last_meeting_text(last_game.get("previous_meeting"), opp, "Previous meeting")
        if previous:
            lines.append(previous.replace(f"with {opp}:", f"with {opp} this season:", 1))
        series = _series_words(last_game.get("season_series"))
        if series:
            lines.append(f"Season series vs {opp}: {series}")

    next_game = data.get("next_game")
    if next_game:
        lines.append(
            f"Next game: {_next_game_when(next_game)}, "
            f"{_where_words(next_game.get('home_or_away', ''), next_game.get('opponent', ''))}"
        )
        meeting = (data.get("next_game_preview") or {}).get("last_meeting")
        meeting_text = _last_meeting_text(meeting, next_game.get("opponent", ""))
        if meeting_text:
            lines.append(meeting_text)

    notes = data.get("schedule_notes")
    schedule = _schedule_note_text(notes, next_game)
    if schedule:
        lines.append(f"Schedule: {schedule}")
    b2b = _back_to_back_text(notes, next_game)
    if b2b:
        lines.append(f"Back-to-back: {b2b}")

    gap = division_gap_text(data.get("division_gap")) if not data.get("playoff_bracket") else ""
    if gap:
        lines.append(gap)
    lines.extend(_goalie_starts_lines(data.get("goalie_starts")))
    lines.extend(_point_streak_lines(data.get("point_streaks")))
    return lines


def _goal_log_lines(last_game: dict) -> list[str]:
    """Goal-by-goal log with periods, team tags, assists and strength."""
    scoring = last_game.get("scoring_summary", [])
    if not scoring:
        return []
    lines = ["Goal log:"]
    for period in scoring:
        for g in period.get("goals", []):
            assists = f" ({', '.join(g['assists'])})" if g.get("assists") else " (unassisted)"
            strength = f" [{g['strength']}]" if g.get("strength", "EV") != "EV" else ""
            phase = f" ({g['phase']})" if g.get("phase") else ""
            lines.append(
                f"  {period['period_label']} {g.get('time', '')}{phase} — "
                f"{g.get('team', '')} — {g.get('scorer', '')}{assists}{strength}"
            )
    if last_game.get("decided_in_shootout"):
        lines.append("  Decided in a shootout.")
    return lines


KEY_FACTS_HEADER = "=== KEY FACTS (computed in code; use exactly as given, do not recalculate) ==="


def _format_weekday_month_day(dt: datetime) -> str:
    """Format as 'Saturday, April 4' without platform-specific strftime."""
    return f"{dt.strftime('%A')}, {dt.strftime('%B')} {dt.day}"


# --- Preview mode (python main.py --preview) --------------------------------
# When enabled, every prompt is written to PREVIEW_PROMPT_DIR, and without an
# API key for the configured provider, a stub client returns clearly marked placeholder text.
_preview: dict = {"prompt_dir": None, "counts": {}}

_STUB_TEXT = {
    "generate_digest": (
        "[STUB BRIEFING — no LLM API key; see preview/prompts/generate_digest.txt]\n\n"
        "[STUB paragraph two.]\n\n[STUB paragraph three.]"
    ),
    "generate_what_we_learned": (
        "1. [STUB takeaway one]\n2. [STUB takeaway two]\n3. [STUB takeaway three]"
    ),
    "generate_subject": "[STUB SUBJECT]",
    "generate_fine_print": "[STUB FINE PRINT]",
    "generate_on_this_day": "[STUB ON THIS DAY]",
    "generate_playoff_race_analysis": "- [STUB race bullet]",
}


def enable_preview(prompt_dir: str) -> None:
    """Record every prompt to prompt_dir; stub the model if no API key is set."""
    os.makedirs(prompt_dir, exist_ok=True)
    for name in os.listdir(prompt_dir):
        if name.endswith(".txt"):
            os.remove(os.path.join(prompt_dir, name))
    _preview["prompt_dir"] = prompt_dir
    _preview["counts"] = {}


class _StubMessages:
    """Stands in for client.messages in preview mode without an API key."""

    def create(self, name: str = "", **kwargs):
        text = _STUB_TEXT.get(name, f"[STUB {name}]")
        block = SimpleNamespace(type="text", text=text)
        return SimpleNamespace(content=[block], stop_reason="end_turn")


def _get_client():
    """A client for the configured provider (llm.py), the preview stub, or None.

    None means no API key for the configured provider: generators fall back to
    their default text (and generate_digest raises).
    """
    if not llm.available():
        if _preview["prompt_dir"]:
            return SimpleNamespace(messages=_StubMessages())
        return None
    return SimpleNamespace(messages=_ProviderMessages())


class _ProviderMessages:
    """Gives every generator the same call shape (messages.create) for any provider."""

    def create(self, *, system: str, messages: list[dict], max_tokens: int, **_ignored):
        user = "\n\n".join(m["content"] for m in messages if m["role"] == "user")
        result = llm.complete(system, user, max_tokens)
        block = SimpleNamespace(type="text", text=result.text)
        return SimpleNamespace(content=[block], stop_reason=result.stop_reason)


def _record_prompt(name: str, kwargs: dict) -> None:
    """Preview mode: write the exact system and user text sent for one call."""
    prompt_dir = _preview["prompt_dir"]
    if not prompt_dir:
        return
    n = _preview["counts"].get(name, 0) + 1
    _preview["counts"][name] = n
    suffix = "" if n == 1 else f"_{n}"
    path = os.path.join(prompt_dir, f"{name}{suffix}.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"model: {kwargs.get('model')}\nmax_tokens: {kwargs.get('max_tokens')}\n\n")
        f.write("=== SYSTEM ===\n" + str(kwargs.get("system", "")) + "\n\n")
        for m in kwargs.get("messages", []):
            f.write(f"=== {m['role'].upper()} ===\n{m['content']}\n\n")


def _call_api(client, name: str, **kwargs):
    """Send one generator's prompt to the configured model (retries live in llm.py).

    Args:
        client: From _get_client() (provider adapter or the preview stub).
        name: The generator making the call; names the preview prompt file.
    """
    _record_prompt(name, kwargs)
    if isinstance(getattr(client, "messages", None), _StubMessages):
        return client.messages.create(name=name, **kwargs)
    return client.messages.create(**kwargs)


def _get_our_series(data: dict) -> tuple[str, dict, bool] | tuple[None, None, None]:
    """Return (round_name, series, is_active) for the most relevant series involving our team.

    is_active is True when the series is genuinely in progress (no team has 4 wins
    and the API winner field is not yet set). is_active is False when the series is
    complete — the API may not have set winner yet when the clinching game just ended,
    so we treat any series where either team reaches 4 wins as finished.
    Falls back to the most recently seen series involving our team if none is active.
    """
    bracket = data.get("playoff_bracket")
    if not bracket:
        return None, None, None
    last_round, last_series = None, None
    for round_dict in bracket.get("rounds", []):
        for series in round_dict.get("series", []):
            if not series.get("involves_us"):
                continue
            last_round, last_series = round_dict["name"], series
            top_wins = series.get("top_wins", 0)
            bottom_wins = series.get("bottom_wins", 0)
            if series.get("winner") is None and top_wins < 4 and bottom_wins < 4:
                return round_dict["name"], series, True
    if last_series is not None:
        return last_round, last_series, False
    return None, None, None


def _series_status_str(series: dict) -> str:
    """Return a human-readable series result, computed from win counts.

    Uses win counts directly so the string is accurate even when the NHL API
    has not yet set the winner field (e.g. immediately after the clinching game).
    """
    top = series.get("top_seed", "")
    bottom = series.get("bottom_seed", "")
    top_wins = series.get("top_wins", 0)
    bottom_wins = series.get("bottom_wins", 0)
    if top_wins == bottom_wins:
        return f"Series tied {top_wins}–{bottom_wins}" if top_wins > 0 else ""
    winner = series.get("winner") or (top if top_wins > bottom_wins else bottom)
    leader_wins = max(top_wins, bottom_wins)
    trailer_wins = min(top_wins, bottom_wins)
    verb = "wins" if leader_wins == 4 else "leads"
    return f"{winner} {verb} {leader_wins}–{trailer_wins}"


def _format_data_for_prompt(data: dict) -> str:
    """Format the structured NHL data dict into a readable text block for the prompt.

    Args:
        data: Dictionary returned by nhl.get_team_data().

    Returns:
        Human-readable string summarising all available data fields.
    """
    lines = [KEY_FACTS_HEADER, *_key_facts_lines(data), ""]

    last_game = data.get("last_game")
    if last_game:
        result = last_game.get("result", "?")
        ending = {"OT": " (OT)", "SO": " (SO)"}.get(last_game.get("period_type", ""), "")
        our_score = last_game.get("our_score", 0)
        opp_score = last_game.get("opponent_score", 0)
        opponent = last_game.get("opponent", "Unknown")
        venue = last_game.get("home_or_away", "home").capitalize()
        date = last_game.get("date", "Unknown date")

        lines.append("=== LAST GAME ===")
        lines.append(
            f"Result: {result}{ending} | {NICK} {our_score}, {opponent} {opp_score} ({venue}) on {date}"
        )

        # Season series vs opponent
        ss = last_game.get("season_series")
        if ss:
            lines.append(f"Season series vs {opponent}: {ss['label']} (W-L-OTL)")

        lines.extend(_goal_log_lines(last_game))

        top_skaters = last_game.get("top_skaters", [])
        if top_skaters:
            lines.append(f"Top {ABBR} performers:")
            for skater in top_skaters:
                lines.append(
                    f"  - {skater['name']}: {skater['goals']}G {skater['assists']}A "
                    f"({skater['points']} pts) | TOI: {skater['toi']}"
                )

        goalie = last_game.get("goalie")
        if goalie:
            save_pct_display = f"{goalie['save_pct']:.3f}" if goalie.get("save_pct") else "N/A"
            lines.append(
                f"{ABBR} goalie: {goalie['name']} — {goalie['saves']}/{goalie['shots_against']} "
                f"saves, .{save_pct_display.lstrip('0').lstrip('.')[:3]} SV%"
            )

        opp_goalie = last_game.get("opponent_goalie")
        if opp_goalie:
            lines.append(
                f"{opponent} goalie: {opp_goalie['name']} — "
                f"{opp_goalie['saves']}/{opp_goalie['shots_against']} saves"
            )

        sog = last_game.get("team_stats", {}).get("ours", {}).get("sog")
        if sog:
            lines.append(f"{ABBR} shots on goal: {sog}")

        # Three stars
        three_stars = last_game.get("three_stars", [])
        if three_stars:
            lines.append("Three stars:")
            for s in three_stars:
                lines.append(f"  {s['star']}. {s['name']} ({s['team']}) — {s.get('summary', '')}")
    else:
        lines.append("=== LAST GAME ===")
        lines.append("No completed game found in the last two weeks.")

    standings = data.get("standings")
    if data.get("playoff_bracket"):
        round_name, series, is_active = _get_our_series(data)
        if series:
            lines.append("")
            lines.append("=== PLAYOFF SERIES ===")
            status = _series_status_str(series)
            lines.append(f"{round_name}: {status}" + ("" if is_active else " (series complete)"))
    elif standings:
        lines.append("")
        lines.append("=== STANDINGS ===")
        lines.append(
            f"Record: {standings['wins']}-{standings['losses']}-{standings['ot_losses']} "
            f"| {standings['points']} pts | .{str(standings['point_pct']).lstrip('0').lstrip('.')[:3]} pts% "
            f"| {DIV} Division: #{standings['division_rank']} "
            f"| Streak: {standings['streak']}"
        )

    magic_number = data.get("magic_number")
    if magic_number is not None:
        if magic_number == 0:
            lines.append("Playoff spot: CLINCHED")
        else:
            lines.append(f"Magic number to clinch playoffs: {magic_number}")

    recent_form = data.get("recent_form")
    if recent_form:
        lines.append(f"Recent form (last 10): {recent_form['record']}")

    # Top scorers
    top_scorers = data.get("top_scorers", [])
    if top_scorers:
        lines.append("")
        label = "PLAYOFFS" if data.get("playoff_scorers") else "SEASON"
        lines.append(f"=== TOP SCORERS ({label}) ===")
        for p in top_scorers[:3]:
            lines.append(
                f"  {p['name']}: {p['goals']}G {p['assists']}A {p['points']}pts in {p['games_played']} GP"
            )

    player_context = data.get("player_context", {})
    if player_context:
        lines.append("")
        lines.append(_format_player_context(player_context))

    # Player of week
    pow_data = data.get("player_of_week")
    if pow_data:
        lines.append(
            f"Player of the week (last 5 GP): {pow_data['name']} — "
            f"{pow_data['goals']}G {pow_data['assists']}A {pow_data['points']}pts"
        )

    # Milestones
    milestones = data.get("milestones", [])
    if milestones:
        lines.append("Milestone watch:")
        for m in milestones:
            lines.append(f"  {m['name']}: {m['needed']} {m['stat']} from {m['next_milestone']}")

    next_game = data.get("next_game")
    if next_game:
        lines.append("")
        lines.append("=== NEXT GAME ===")
        next_line = (
            f"{_next_game_when(next_game)}, "
            f"{_where_words(next_game.get('home_or_away', ''), next_game.get('opponent', ''))}"
        )
        if next_game.get("venue"):
            next_line += f" ({next_game['venue']})"
        lines.append(next_line)
    else:
        lines.append("")
        lines.append("=== NEXT GAME ===")
        lines.append("No upcoming game found in the schedule.")

    # Season game log — gives the model historical context across the season
    game_log = data.get("game_log", "")
    if game_log:
        lines.append("")
        lines.append(game_log)

    # Current news headlines — silently inform the model without being shown in the email
    news_headlines = data.get("news_headlines", [])
    if news_headlines:
        lines.append("")
        lines.append(
            f"=== CURRENT {NICK.upper()} NEWS (background only: do not cite sources or take any figure from these) ==="
        )
        for headline in news_headlines:
            lines.append(f"  - {headline}")

    # Player availability — silently inform the model so it can explain absences naturally
    injuries = data.get("injuries", [])
    if injuries:
        lines.append("")
        lines.append(
            "=== PLAYER AVAILABILITY (these players DID NOT PLAY — do not describe their in-game performance) ==="
        )
        for inj in injuries:
            lines.append(f"  - {inj['player']}: {inj['status']}")

    return "\n".join(lines)


def _format_player_context(player_context: dict) -> str:
    """Format career context snapshots into a compact prompt block.

    Args:
        player_context: Dict mapping player name → snapshot dict from nhl.get_player_career_context().

    Returns:
        Formatted text block, or empty string if no data.
    """
    if not player_context:
        return ""

    lines = ["=== PLAYER CAREER CONTEXT (last 3 seasons + current pace) ==="]
    for snapshot in player_context.values():
        name = snapshot.get("name", "?")
        pos = snapshot.get("position", "?")
        note = snapshot.get("note")
        note_str = f", NOTE: {note}" if note else ""

        if pos == "G":
            career_sv = snapshot.get("career_avg_sv_pct")
            current_sv = snapshot.get("current_sv_pct")
            gp = snapshot.get("current_gp", 0)
            past = snapshot.get("season_by_season", [])
            past_str = (
                "/".join(f".{str(s['sv_pct']).lstrip('0').lstrip('.')}" for s in past)
                if past
                else "N/A"
            )
            if career_sv and current_sv:
                career_str = f".{str(career_sv).lstrip('0').lstrip('.')}"
                current_str = f".{str(current_sv).lstrip('0').lstrip('.')}"
                trend = snapshot.get("trend", "on_pace")
                trend_label = {
                    "above": "above avg",
                    "below": "below avg",
                    "on_pace": "at career norm",
                }.get(trend, "")
                lines.append(
                    f"{name} ({pos}): Career avg {career_str} SV% | "
                    f"This season: {current_str} ({trend_label}{note_str}) in {gp} GP | "
                    f"3-yr: {past_str}"
                )
            else:
                lines.append(f"{name} ({pos}): {gp} GP this season{note_str}")
        else:
            career_pts = snapshot.get("career_avg_points_82")
            career_g = snapshot.get("career_avg_goals_82")
            current_pts_pace = snapshot.get("current_points_82_pace")
            current_pts = snapshot.get("current_points", 0)
            current_g = snapshot.get("current_goals", 0)
            gp = snapshot.get("current_gp", 0)
            trend_pct = snapshot.get("trend_pct", 0.0)
            trend = snapshot.get("trend", "on_pace")
            past = snapshot.get("season_by_season", [])
            past_pts_str = "/".join(str(s["pts"]) for s in past) if past else "N/A"
            trend_sign = "+" if trend_pct > 0 else ""
            trend_label = {
                "above": f"{trend_sign}{trend_pct:.0f}% above avg",
                "below": f"{trend_pct:.0f}% below avg",
                "on_pace": "on pace",
            }.get(trend, "")
            if career_pts and current_pts_pace:
                lines.append(
                    f"{name} ({pos}): Career avg {career_pts} pts/82, {career_g}G/82 | "
                    f"This season: {current_pts}pts/{current_g}G in {gp}GP, on pace {current_pts_pace} pts ({trend_label}{note_str}) | "
                    f"3-yr pts: {past_pts_str}"
                )
            else:
                lines.append(
                    f"{name} ({pos}): {current_pts}pts/{current_g}G in {gp}GP this season{note_str}"
                )

    return "\n".join(lines)


def _top_skater_career_note(data: dict) -> str:
    """Return a one-liner career context note for the top skater in last night's game.

    Used to enrich the What We Learned prompt without the full context block.

    Args:
        data: Full pipeline data dict.

    Returns:
        One-sentence career context string, or "" if unavailable.
    """
    player_context = data.get("player_context", {})
    last_game = data.get("last_game", {})
    top_skaters = (last_game or {}).get("top_skaters", [])
    if not top_skaters or not player_context:
        return ""

    top_name = top_skaters[0].get("name", "")
    snapshot = player_context.get(top_name)
    if not snapshot:
        return ""

    trend = snapshot.get("trend", "on_pace")
    trend_pct = snapshot.get("trend_pct", 0.0)
    career_pts = snapshot.get("career_avg_points_82")
    note = snapshot.get("note")

    if note:
        return f"Career context: {top_name} is {note} this season."
    if career_pts and trend != "on_pace":
        sign = "above" if trend == "above" else "below"
        return (
            f"Career context: {top_name} is currently {abs(trend_pct):.0f}% "
            f"{sign} their {career_pts}-pts/82 career average."
        )
    return ""


WWL_TARGET_WORDS = 28  # asked of the model
WWL_MAX_WORDS = 35  # over this, regenerate once, then drop


def _word_count(text: str) -> int:
    return len(text.split())


def _parse_takeaways(raw: str) -> list[str]:
    """Numbered lines ('1. ...') → up to three takeaway strings."""
    lines = [
        re.sub(r"^\d+[.)]\s*", "", line.strip())
        for line in raw.strip().splitlines()
        if line.strip() and line.strip()[0].isdigit()
    ]
    return [item for item in lines if item][:3]


def generate_what_we_learned(data: dict, briefing: str = "") -> list[str]:
    """Generate 3 punchy takeaways from the most recent game.

    Runs on every send. Returns [] on any error so
    the digest still sends.

    Args:
        data: Dictionary returned by nhl.get_team_data().
        briefing: The finished briefing, so the takeaways can add to it rather
            than repeat it.

    Returns:
        List of 3 one-sentence takeaway strings, or [] if generation fails.
    """
    client = _get_client()
    if not client:
        return []

    last_game = data.get("last_game")
    if not last_game:
        return []

    result = last_game.get("result", "?")
    our_score = last_game.get("our_score", 0)
    opp_score = last_game.get("opponent_score", 0)
    opponent = last_game.get("opponent", "the opponent")
    top_skaters = last_game.get("top_skaters", [])
    goalie = last_game.get("goalie")
    stars = last_game.get("three_stars", [])

    ending = {"OT": " in overtime", "SO": " in a shootout"}.get(
        last_game.get("period_type", ""), ""
    )
    context_parts = [
        f"{NAME} {result} vs {opponent}: {ABBR} {our_score}, {opponent} {opp_score}{ending}.",
    ]
    if top_skaters:
        best = top_skaters[0]
        context_parts.append(
            f"Top {ABBR} performer: {best['name']} ({best['goals']}G {best['assists']}A)."
        )
    if goalie:
        context_parts.append(
            f"{ABBR} goalie: {goalie['name']} — {goalie['saves']}/{goalie['shots_against']} saves."
        )
    if stars:
        context_parts.append(f"1st star: {stars[0]['name']} ({stars[0].get('team', '?')}).")

    career_note = _top_skater_career_note(data)
    if career_note:
        context_parts.append(career_note)

    injuries = data.get("injuries", [])
    if injuries:
        inj_lines = [
            f"{inj['player']} ({inj.get('position', '?')}): {inj['status']}" for inj in injuries
        ]
        context_parts.append("Unavailable: " + "; ".join(inj_lines) + ".")

    context = " ".join(context_parts)

    # Append roster context so the model understands each player's position and
    # scoring rank — prevents treating a high-scoring defenceman as an anomaly.
    player_context = data.get("player_context")
    roster_block = _format_player_context(player_context) if player_context else ""

    when = _last_game_when(last_game)
    sections = [
        KEY_FACTS_HEADER,
        *_key_facts_lines(data),
        "",
        f"The game, played {when}: {context}",
        *_goal_log_lines(last_game),
    ]
    if briefing:
        sections += [
            "",
            "=== TODAY'S BRIEFING (already in the email — do not repeat its points) ===",
            briefing,
        ]
    sections += [
        "",
        "What did we learn? Give three takeaways that add something the briefing did not say. "
        "At least one should look ahead, using the next game and schedule in KEY FACTS.",
    ]
    user_content = "\n".join(sections)
    if roster_block:
        user_content += f"\n\nRoster context (use to accurately characterise player roles — do not summarise this block directly):\n{roster_block}"

    system = (
        f"You are a sharp NHL beat reporter who covers the {NAME} daily "
        "and knows every player on every NHL roster by name, position, and role. "
        f"Write exactly 3 takeaways from the {NICK}' most recent game. Each takeaway is one "
        f"sentence with one idea, at most {WWL_TARGET_WORDS} words. "
        "Refer to when it was played only as KEY FACTS states it. "
        "Each takeaway should connect the game to something that matters: the standings, "
        "a trend, a player's trajectory, or what it means going forward. "
        "Use dry, observational wit — humor comes from the situation, not from quips. "
        "Be honest about problems without manufactured outrage. Number them 1, 2, 3. "
        "CRITICAL — goalies: any claim about a goalie's run of games (consecutive starts, "
        "recent form) must come from the goalie starts lines in KEY FACTS, which list every "
        "recent start in order. "
        "CRITICAL — factual accuracy: only reference a player's position or role if it appears "
        "in the roster context or availability data provided. Never infer positions from memory. "
        "Numbers, streaks and records come only from the data; never call anything a career "
        "high, a record or a first since unless a data line says so. "
        "CRITICAL — time and place: never calculate elapsed time or infer where a game "
        "was played; use only KEY FACTS. "
        "Plain text only. " + NAME_RULES
    )

    def _ask() -> list[str]:
        message = _call_api(
            client,
            name="generate_what_we_learned",
            model=MODEL_ID,
            max_tokens=350,
            system=system,
            messages=[{"role": "user", "content": user_content}],
        )
        return _parse_takeaways(message.content[0].text)

    try:
        takeaways = _ask()
    except Exception as e:
        logger.warning("What we learned generation failed: %s", e)
        run_report.record("What We Learned", "model call failed")
        return []

    if any(_word_count(t) > WWL_MAX_WORDS for t in takeaways):
        logger.info(
            "What we learned: a takeaway is over %d words — regenerating once", WWL_MAX_WORDS
        )
        try:
            takeaways = _ask()
        except Exception as e:
            logger.warning("What we learned regeneration failed: %s — keeping the first set", e)
        kept = [t for t in takeaways if _word_count(t) <= WWL_MAX_WORDS]
        if len(kept) < len(takeaways):
            logger.info(
                "What we learned: dropped %d over-long takeaway(s)", len(takeaways) - len(kept)
            )
        takeaways = kept

    logger.info("What we learned generated: %d takeaways", len(takeaways))
    return takeaways


_FINE_PRINT_STYLES = [
    "fake legal disclaimer — dry, absurdist, overly specific legalese",
    "fake product recall / safety warning — treat the email itself as a hazardous consumer product",
    "passive-aggressive HR memo — corporate politeness barely masking frustration",
    "fake FDA nutrition label blurb — as if the email comes with a nutritional facts panel",
    "absurdist fortune cookie — cryptic one-liner that barely relates to hockey",
    f"fake warranty voided notice — list ridiculous actions that void the reader's {NICK} fandom warranty",
    "overly sincere apology from management — earnest corporate damage control",
    f"breakup note from the {NICK} — they're not mad, just disappointed",
]


def generate_fine_print(data: dict) -> str:
    """Generate a short funny tagline based on the game result.

    Rotates through different comedy styles (legal disclaimer, product recall,
    HR memo, etc.) based on the day of the year so the format varies from
    email to email. Always included at the bottom of the email regardless of
    whether there was a game. Returns a fallback string on any error.

    Args:
        data: Dictionary returned by nhl.get_team_data().

    Returns:
        One-sentence tagline string.
    """
    fallback = (
        f"The {SETTINGS.newsletter_name} is not responsible for any joy, heartbreak, "
        "or superstitious rituals this email may have caused."
    )
    client = _get_client()
    if not client:
        return fallback

    last_game = data.get("last_game")
    standings = data.get("standings")

    today = _reference_day(data)
    today_str = _format_long_date(today)
    style = _FINE_PRINT_STYLES[today.timetuple().tm_yday % len(_FINE_PRINT_STYLES)]

    context_parts = [f"Date: {today_str}."]
    if last_game:
        opponent = last_game.get("opponent", "someone")
        our_score = last_game.get("our_score", 0)
        opp_score = last_game.get("opponent_score", 0)
        margin = abs(our_score - opp_score)
        margin_words = {1: "one-goal", 2: "two-goal", 3: "three-goal"}.get(margin, f"{margin}-goal")
        result = _result_words(
            last_game.get("result", ""), our_score, opp_score, last_game.get("period_type")
        )
        context_parts.append(
            f"The {NICK} {result} against {opponent} {_last_game_when(last_game)}: "
            f"a {margin_words} margin."
        )
    if standings and not data.get("playoff_bracket"):
        context_parts.append(f"They are #{standings['division_rank']} in the {DIV}.")

    context = (
        " ".join(context_parts) if context_parts else f"The {NICK} exist and are a hockey team."
    )

    try:
        message = _call_api(
            client,
            name="generate_fine_print",
            model=MODEL_ID,
            max_tokens=200,
            system=(
                f"You write the fine print at the bottom of an {NAME} daily email digest. "
                f"Write exactly one sentence of at most 25 words in this style: {style}. "
                f"Reference the actual game situation subtly. Any game fact you mention (score, "
                f"margin, how it ended, when it was played) must match the data exactly. "
                f"No quotes around the output. Plain text only."
            ),
            messages=[{"role": "user", "content": context}],
        )
        if getattr(message, "stop_reason", None) == "max_tokens":
            logger.warning("Fine print hit max_tokens — using fallback")
            return fallback
        text = message.content[0].text.strip().rstrip(".")
        logger.info("Fine print generated (style: %s)", style.split("—")[0].strip())
        return text
    except Exception as e:
        logger.warning("Fine print generation failed: %s", e)
        return fallback


# Franchise people whose Wikipedia events count for On This Day (config [on_this_day] people)
TEAM_PEOPLE = list(SETTINGS.people)

_TEAM_NAME_RE = re.compile(rf"\b{re.escape(NAME)}\b", re.IGNORECASE)
_NICKNAME_RE = re.compile(rf"\b{re.escape(NICK)}\b", re.IGNORECASE)
_HOCKEY_CONTEXT_RE = re.compile(rf"\b({re.escape(PLACE)}|NHL|hockey|Stanley Cup)\b", re.IGNORECASE)
_PEOPLE_RE = (
    re.compile(r"\b(" + "|".join(re.escape(n) for n in TEAM_PEOPLE) + r")\b", re.IGNORECASE)
    if TEAM_PEOPLE
    else None
)


def is_team_event(text: str) -> bool:
    """True if a Wikipedia event is plausibly about our team.

    Matches whole words only (so "boilers" never matches "Oilers"): the full
    team name, a person from config [on_this_day] people, or the bare nickname
    when the text also says the team's place, NHL, hockey or Stanley Cup (which
    rules out e.g. the Houston Oilers).
    """
    if _TEAM_NAME_RE.search(text) or (_PEOPLE_RE and _PEOPLE_RE.search(text)):
        return True
    return bool(_NICKNAME_RE.search(text) and _HOCKEY_CONTEXT_RE.search(text))


def generate_on_this_day(ref_date: date | None = None) -> dict | None:
    """Generate an 'On This Day in team history' note for the run's reference date.

    Queries the Wikipedia 'on this day' API for an event about our team and,
    if one is found, asks the model for a one-liner built only from that text.
    The model answers SKIP when the event is not really about our team or a
    listed person, and the card is hidden. There is no model-memory
    fallback: with no Wikipedia event the card is hidden.

    Args:
        ref_date: The run's reference date (nhl.reference_date); defaults to
            today in the local time zone.

    Returns:
        Dict with 'text' (one-sentence note) and 'source' ('wikipedia'), or None.
    """
    client = _get_client()
    if not client:
        return None

    today = ref_date or _local_now().date()
    month = today.month
    day = today.day
    date_label = f"{today.strftime('%B')} {day}"

    wiki_event = None
    try:
        url = f"https://en.wikipedia.org/api/rest_v1/feed/onthisday/events/{month}/{day}"
        resp = requests.get(url, timeout=10, headers={"User-Agent": "NHLDaily/1.0"})
        if resp.status_code == 200:
            matches = []
            for event in resp.json().get("events", []):
                text = event.get("text", "")
                if is_team_event(text):
                    entry = {"year": event.get("year"), "text": text}
                    matches.append(entry)
            wiki_event = matches[0] if matches else None
    except Exception as e:
        logger.warning("Wikipedia on-this-day lookup failed: %s", e)
        run_report.record("On This Day", "Wikipedia unavailable")

    if not wiki_event:
        logger.info("On this day: no %s event on Wikipedia for %s — card hidden", NICK, date_label)
        return None

    try:
        prompt = (
            f"On this day ({date_label}) in {wiki_event['year']}: {wiki_event['text']}\n\n"
            f"Write exactly one punchy sentence putting this in context for a die-hard {NICK} fan. "
            "Use only the facts in the text above: add no other dates, numbers, records or names.\n\n"
            + (
                f"If this event is not about the {NAME} or one of these people, answer exactly "
                f"SKIP and nothing else: {', '.join(TEAM_PEOPLE)}."
                if TEAM_PEOPLE
                else f"If this event is not about the {NAME}, answer exactly SKIP and nothing else."
            )
        )
        source = "wikipedia"

        message = _call_api(
            client,
            name="generate_on_this_day",
            model=MODEL_ID,
            max_tokens=100,
            system=(
                f"You are a passionate {NAME} historian. "
                "Write exactly one sentence. Be specific, punchy, and factual. "
                "Output only the final sentence — never include self-corrections, "
                "hedging, 'wait', 'actually', or any mid-sentence revisions. "
                "State only facts present in the supplied text."
            ),
            messages=[{"role": "user", "content": prompt}],
        )
        text = message.content[0].text.strip().rstrip(".")
        if text.strip().strip('"').upper() == "SKIP":
            logger.info(f"On this day: model says the event is not about the {NICK} — card hidden")
            return None
        logger.info("On this day generated (source: %s): %s", source, text[:60])
        return {"text": text, "source": source}
    except Exception as e:
        logger.warning("On this day generation failed: %s", e)
        run_report.record("On This Day", "model call failed")
        return None


def generate_playoff_race_analysis(data: dict) -> str:
    """Generate a short AI analysis of the playoff race and tonight's key games.

    Only runs during the regular season, once we have played
    MAGIC_NUMBER_MIN_GP games, and while they have not yet clinched.
    Returns an empty string otherwise or on any error so the digest still sends.

    Args:
        data: Dictionary returned by nhl.get_team_data().

    Returns:
        Plain text analysis string, or "" if unavailable.
    """
    client = _get_client()
    if not client:
        return ""

    playoff_race = data.get("playoff_race")
    if not playoff_race or playoff_race.get("clinched"):
        return ""
    if playoff_race.get("our_gp", 0) < MAGIC_NUMBER_MIN_GP:
        return ""  # too early in the season for race prose (no API call)

    standings = data.get("standings")
    in_div_spot = playoff_race.get("in_division_spot", False)
    our_div_rank = playoff_race.get("our_div_rank", "?")

    if in_div_spot:
        our_status = (
            f"HOLDING A DIVISION SPOT: #{our_div_rank} in the {DIV}. "
            f"The top 3 teams in each division earn automatic playoff berths — "
            f"{PLACE} does NOT need a wild card. Do not describe them as chasing a wild card."
        )
    else:
        our_status = f"#{our_div_rank} in the {DIV} (outside top 3) — needs a wild card spot to make playoffs."

    lines = [
        f"*** {PLACE.upper()}'S PLAYOFF STATUS: {our_status} ***",
        f"Points: {playoff_race['our_points']} | Games remaining: {playoff_race['our_games_remaining']}",
    ]
    if standings:
        lines.append(f"Record: {standings['wins']}-{standings['losses']}-{standings['ot_losses']}")

    if in_div_spot:
        lines.append(
            f"\n{DIV} teams that could push {ABBR} out of a division spot + wild card bubble:"
        )
    else:
        lines.append(f"\n{CONF} Conference wild card bubble:")

    for t in playoff_race.get("bubble_teams", []):
        tonight = (
            f" — plays {t['tonight_opponent']} tonight"
            if t.get("tonight_opponent")
            else " — off tonight"
        )
        division = t.get("division") or "?"
        div_label = f" ({division} #{t['div_rank']})" if t.get("div_rank") else f" ({division})"
        lines.append(
            f"  {t['abbrev']}{div_label}: {t['points']} pts "
            f"({t['games_remaining']} GP left, max {t['max_possible_pts']}){tonight}"
        )

    key_games = playoff_race.get("key_games_tonight", [])
    if key_games:
        lines.append(f"\nKey games tonight that affect {PLACE}:")
        for g in key_games:
            lines.append(f"  {g['away']} @ {g['home']}")
    else:
        lines.append("\nNo relevant games tonight.")

    context = "\n".join(lines)

    try:
        message = _call_api(
            client,
            name="generate_playoff_race_analysis",
            model=MODEL_ID,
            max_tokens=600,
            system=(
                f"You are a sharp NHL analyst writing for a die-hard {NAME} fan. "
                "Be direct and opinionated. Use hockey shorthand. No fluff. "
                "IMPORTANT: plain text only — no Markdown, no asterisks, no ## headers, "
                "no bold, no ---, no backticks. Use a plain dash (-) for bullet points."
            ),
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"Here's the current playoff race situation:\n\n{context}\n\n"
                        f"Write 2-3 punchy sentences on where the {NICK} stand. "
                        f"IMPORTANT: if the data says {ABBR} is in a division playoff spot, "
                        "do NOT say they are chasing a wild card — they are already in. "
                        "Focus on whether their division spot is secure and what could threaten it. "
                        "Each team is tagged with its division: call a team a division rival only "
                        f"if it is tagged {DIV}. "
                        "Then at most three bullets for tonight. Each bullet names one game and the "
                        f"one result {PLACE} wants from it, and why. Leave out any game whose result "
                        f"does not change {PLACE}'s position. "
                        "If no game tonight matters, just summarise the race. "
                        "Plain text only — no Markdown formatting whatsoever."
                    ),
                }
            ],
        )
        analysis = message.content[0].text.strip()
        logger.info("Playoff race analysis generated (%d words)", len(analysis.split()))
        return analysis
    except Exception as e:
        logger.warning("Playoff race analysis generation failed: %s", e)
        run_report.record("Playoff race analysis", "model call failed")
        return ""


def generate_subject(data: dict) -> str:
    """Generate a punchy email subject line that reflects the team's situation today.

    Summarises the last game result (if any), current streak or standings position,
    and/or tonight's game in under ~60 characters. Falls back to a plain date string
    on any error so the email always sends.

    Args:
        data: Dictionary returned by nhl.get_team_data().

    Returns:
        Subject line string.
    """
    today = _format_weekday_month_day(_reference_day(data))
    fallback = f"{SETTINGS.newsletter_name} \u2014 {today}"

    client = _get_client()
    if not client:
        return fallback

    last_game = data.get("last_game")
    standings = data.get("standings")
    next_game = data.get("next_game")

    parts = []
    days_ago = None
    if last_game:
        days_ago = last_game.get("days_ago")
        result = _result_words(
            last_game.get("result", ""),
            last_game.get("our_score", 0),
            last_game.get("opponent_score", 0),
            last_game.get("period_type"),
        )
        opponent = last_game.get("opponent", "")
        parts.append(
            f"Last game, played {_last_game_when(last_game)}: {NICK} {result} vs {opponent}."
        )
    if data.get("playoff_bracket"):
        _, series, is_active = _get_our_series(data)
        if series:
            status = _series_status_str(series)
            label = "Series" if is_active else "Series result"
            parts.append(f"{label}: {status}.")
    elif standings:
        parts.append(
            f"Record: {standings['wins']}-{standings['losses']}-{standings['ot_losses']}, "
            f"#{standings['division_rank']} in {DIV}, streak: {standings['streak']}."
        )
    next_is_today = bool(next_game and next_game.get("is_today"))
    if next_game:
        parts.append(
            f"Next game: {_next_game_when(next_game)}, "
            f"{_where_words(next_game.get('home_or_away', ''), next_game.get('opponent', ''))}."
        )

    if not parts:
        return fallback

    # Scheduled sends land 0-1 days after a game; the "tonight" lead mainly
    # applies to forced sends days later.
    if days_ago is not None and days_ago >= 2 and next_is_today:
        lead = (
            f"Lead with tonight's game as a scheduling fact (e.g. 'Tonight: {NICK} at Toronto'); "
            "you may add the streak or record."
        )
    else:
        lead = "Lead with the last game's result."
    parts.append(lead)

    context = " ".join(parts)

    try:
        message = _call_api(
            client,
            name="generate_subject",
            model=MODEL_ID,
            max_tokens=30,
            system=(
                f"You write email subject lines for an {NAME} daily digest. "
                "Write exactly one subject line — no quotes, no punctuation at the end, "
                "under 60 characters. Be punchy and specific. Use plain text only. "
                "When combining two independent clauses (e.g. game result and standings "
                "change), separate them with a comma. "
                "Follow the 'Lead with' instruction in the data. Describe how the last game "
                "ended exactly as given (overtime, shootout). If a next game is mentioned, "
                "state it as a scheduling fact only (e.g. 'Colorado up next') — never "
                "predict, imply, or hint at the outcome of a future game."
            ),
            messages=[{"role": "user", "content": context}],
        )
        subject = message.content[0].text.strip().strip('"').rstrip(".")
        logger.info("Subject generated: %s", subject)
        return subject
    except Exception as e:
        logger.warning("Subject generation failed: %s", e)
        return fallback


def generate_digest(data: dict) -> str:
    """Generate an AI-written daily briefing from structured team data.

    Calls the Anthropic API with a system prompt defining the analyst persona
    and a user prompt containing all structured NHL data. Targets 200-250 words.

    Args:
        data: Dictionary returned by nhl.get_team_data().

    Returns:
        Plain text briefing string.

    Raises:
        llm.LLMError: If the model call fails.
        OSError: If the configured provider's API key is not set.
    """
    client = _get_client()
    if not client:
        raise OSError(
            f"{llm.LLM.api_key_env} is not set (needed for [llm] provider = "
            f"{llm.LLM.provider!r}). Add it to your .env file or GitHub secrets."
        )

    formatted_data = _format_data_for_prompt(data)

    user_prompt = f"""Here is today's {NICK} data:

{formatted_data}

Write a daily briefing covering:
1. Last game recap — what happened, the final score, any key moments, and how it was decided
2. Standout performers — highlight the top skater(s) and the goalie if notable
3. What the result means for the {NICK}' position and trajectory. The email already shows the record, points, streak and last-10 on cards: do not restate those numbers; talk only about what they mean
4. A sharp one-liner on the next game — opponent, stakes, tone — drawing on the last meeting and the schedule notes in KEY FACTS

Timing: say "last night" only if KEY FACTS gives the last game as last night. Otherwise refer to it by the weekday KEY FACTS gives.

Facts:
- Numbers, streaks and records come only from the data blocks above. The news headlines are background only: take no figure from them.
- Never call anything a "career high", a "record" or a "first since" unless a data line says so.
- Describe the standings position with the division line in KEY FACTS (e.g. "{DIV}: 1st, 4 points ahead of ..."), in proportion to the gap it gives: a few points with equal games played is a narrow lead, not a runaway.
- When you say when a goal came, use the timing words given in the goal log (early / midway through / late in) exactly.

Target length: 200-250 words. No headers or bullet points — write it as flowing prose, like a radio segment. Be direct and punchy."""

    logger.info("Calling %s", llm.describe())
    message = _call_api(
        client,
        name="generate_digest",
        model=MODEL_ID,
        max_tokens=512,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
    )
    briefing = message.content[0].text.strip()
    logger.info("Digest generated (%d words)", len(briefing.split()))
    return briefing
