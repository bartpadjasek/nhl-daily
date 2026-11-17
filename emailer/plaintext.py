"""Plain-text version of the digest email."""

import run_report
from emailer.theme import (
    ABBR,
    CONF,
    DIV,
    NEWSLETTER,
    NICK,
    _format_date,
    _rank_suffix,
    _save_pct_display,
    divisions_ours_first,
)


def build_plain_text(briefing: str, data: dict, subject_date: str) -> str:
    """Build a plain text fallback version of the email.

    Contains the same information as the HTML version in a readable format.

    Args:
        briefing: Plain-text AI-generated briefing.
        data: Structured data dict from nhl.get_team_data().
        subject_date: Formatted date string, e.g. "Wednesday, March 26".

    Returns:
        Complete plain text string.
    """
    lines = [f"{NEWSLETTER.upper()} — {subject_date.upper()}", "=" * 50, ""]

    last_game = data.get("last_game")
    if last_game:
        result = last_game.get("result", "?")
        our_score = last_game.get("our_score", 0)
        opp_score = last_game.get("opponent_score", 0)
        opponent = last_game.get("opponent", "")
        venue = last_game.get("home_or_away", "home").upper()
        game_date = _format_date(last_game.get("date", ""))
        pt = (last_game.get("period_type") or "").upper()
        ending = f" ({pt})" if pt in ("OT", "SO") else ""

        lines += [
            "LAST GAME",
            "-" * 20,
            f"{ABBR} {our_score} - {opponent} {opp_score}  |  {result}{ending}  |  {venue}  |  {game_date}",
            "",
        ]

        ts = last_game.get("team_stats", {})
        o = ts.get("ours", {})
        p = ts.get("opponent", {})
        lines += [
            f"                {ABBR}     {opponent}",
            f"SOG:            {o.get('sog', '—'):<8}{p.get('sog', '—')}",
            f"PP Goals:       {o.get('pp_goals', '—'):<8}{p.get('pp_goals', '—')}",
            f"Hits:           {o.get('hits', '—'):<8}{p.get('hits', '—')}",
            f"PIM:            {o.get('pim', '—'):<8}{p.get('pim', '—')}",
            f"Blocked Shots:  {o.get('blocked', '—'):<8}{p.get('blocked', '—')}",
            "",
            "Top Performers:",
        ]
        for skater in last_game.get("top_skaters", []):
            lines.append(
                f"  {skater['name']}: {skater['goals']}G {skater['assists']}A "
                f"({skater['points']}pts) — {skater['toi']} TOI"
            )

        lines.append("")
        lines.append("Goaltending:")
        for g in last_game.get("goalies", []):
            dec = f" [{g['decision']}]" if g.get("decision") else ""
            lines.append(
                f"  {g['name']}{dec}: {g['saves']}/{g['shots_against']} "
                f"({_save_pct_display(g['save_pct'])} SV%) — {g['toi']}"
            )
        lines.append("")
    else:
        lines += ["LAST GAME", "-" * 20, "No recently completed game found.", ""]

    lines += ["TODAY'S BRIEFING", "-" * 20, briefing, ""]

    next_game = data.get("next_game")
    if next_game:
        sign = "vs" if next_game.get("home_or_away") == "home" else "@"
        parts = [f"{ABBR} {sign} {next_game['opponent']}", _format_date(next_game.get("date", ""))]
        if next_game.get("time"):
            parts.append(next_game["time"])
        lines += ["NEXT GAME", "-" * 20, "  |  ".join(p for p in parts if p), ""]

    standings = data.get("standings")
    if standings:
        record = f"{standings['wins']}-{standings['losses']}-{standings['ot_losses']}"
        div_rank = standings["division_rank"]
        lines += [
            f"{NICK.upper()} STANDINGS",
            "-" * 20,
            f"Record: {record}  |  {standings['points']} pts  |  "
            f"{DIV}: {div_rank}{_rank_suffix(div_rank)}  |  Streak: {standings.get('streak', '—')}",
            "",
        ]

    playoff_bracket = data.get("playoff_bracket")
    conference_standings = data.get("conference_standings")

    if playoff_bracket:
        lines += ["STANLEY CUP PLAYOFFS", "-" * 20]
        for rnd in playoff_bracket.get("rounds", []):
            lines.append(f"\n{rnd['name'].upper()}")
            for s in rnd.get("series", []):
                winner_note = f"  ({s['winner']} wins)" if s.get("winner") else ""
                lines.append(
                    f"  {s['top_seed']} {s['top_wins']} – {s['bottom_wins']} {s['bottom_seed']}{winner_note}"
                )
        lines.append("")
    elif conference_standings:
        lines += [f"{CONF.upper()} CONFERENCE STANDINGS", "-" * 20]
        for div_name, _ in divisions_ours_first(conference_standings):
            lines.append(f"\n{div_name} Division")
            lines.append(
                f"  {'TEAM':<6} {'GP':>3} {'W':>3} {'L':>3} {'OTL':>4} {'PTS':>4} {'L10':>8} {'STK':>5}"
            )
            for team in conference_standings.get(div_name, []):
                marker = " <--" if team.get("is_us") else ""
                lines.append(
                    f"  {team['abbrev']:<6} {team['gp']:>3} {team['wins']:>3} {team['losses']:>3} "
                    f"{team['ot_losses']:>4} {team['points']:>4} {team['l10']:>8} {team['streak']:>5}{marker}"
                )
        lines.append("")

    lines += [
        "=" * 50,
        f"{NEWSLETTER} — powered by NHL API & AI",
    ]
    missing_line = run_report.footer_line(data.get("missing_data") or [])
    if missing_line:
        lines.append(missing_line)

    return "\n".join(lines)
