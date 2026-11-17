"""Next game cards: Next Up (matchup, preview rows, weather) and Coming Up."""

from datetime import datetime

from emailer.theme import (
    ABBR,
    C_MID_BLUE,
    C_ON_SURFACE,
    C_ON_SURFACE_MED,
    C_PRIMARY_CONT,
    C_ROW_BORDER,
    C_SECONDARY,
    C_SURFACE_LOW,
    C_SURFACE_LOWEST,
    FONT_DATA,
    FONT_EDITORIAL,
    _format_date,
    _save_pct_display,
    _section_marker,
    _team_logo_url,
    esc,
)


def _build_next_game_preview_rows(preview: dict, opponent: str) -> str:
    """Opponent record/streak, season series, last meeting and players to watch.

    Every line is optional: anything the API didn't provide is left out.
    """
    label_css = (
        f"font-family:{FONT_DATA};font-size:10px;font-weight:700;letter-spacing:1.5px;"
        f"color:{C_MID_BLUE};text-transform:uppercase;"
    )
    value_css = f"font-family:{FONT_DATA};font-size:14px;font-weight:600;color:#191c1e;"

    facts: list[tuple[str, str]] = []
    rec = preview.get("opp_record")
    if rec:
        record = f"{rec['wins']}-{rec['losses']}-{rec['ot_losses']} · {rec['points']} pts"
        streak = preview.get("opp_streak")
        if streak and streak != "—":
            record += f" · {streak}"
        facts.append((f"{opponent} record", record))
    ss = preview.get("season_series")
    if ss and (ss.get("wins") or ss.get("losses") or ss.get("ot_losses")):
        facts.append(("Season series", f"{ABBR} {ss['label']} (W-L-OTL)"))
    lm = preview.get("last_meeting")
    if lm:
        verb = {"W": "Won", "L": "Lost", "OTL": "Lost"}.get(lm.get("result", ""), "")
        ending = {"OT": " in OT", "SO": " in a shootout"}.get(lm.get("period_type", ""), "")
        when = _format_date(lm.get("date", ""))
        parts = [f"{verb} {lm['our_score']}-{lm['opponent_score']}{ending}".strip()]
        if lm.get("location"):
            parts.append(esc(lm["location"]))
        if when:
            parts.append(when)
        facts.append(("Last meeting", ", ".join(parts)))

    players: list[tuple[str, str, str]] = []
    tf = preview.get("top_forward")
    if tf:
        players.append(
            (
                "Forward",
                tf["name"],
                f"{tf['goals']}G {tf['assists']}A · {tf['points']} pts in {tf['games_played']} GP",
            )
        )
    td = preview.get("top_defenseman")
    if td:
        players.append(
            (
                "Defence",
                td["name"],
                f"{td['goals']}G {td['assists']}A · {td['points']} pts in {td['games_played']} GP",
            )
        )
    tg = preview.get("top_goalie")
    if tg:
        parts = [f"{tg.get('wins', 0)}W"]
        if tg.get("gaa"):
            parts.append(f"{tg['gaa']:.2f} GAA")
        if tg.get("sv_pct"):
            parts.append(f"{_save_pct_display(tg['sv_pct'])} SV%")
        players.append(("Goalie", tg["name"], " · ".join(parts)))

    if not facts and not players:
        return ""

    rows = ""
    for label, value in facts:
        rows += (
            f'<tr><td style="padding:8px 0;border-bottom:1px solid {C_ROW_BORDER};{label_css}">{label}</td>'
            f'<td style="padding:8px 0;border-bottom:1px solid {C_ROW_BORDER};{value_css}text-align:right;">{value}</td></tr>'
        )
    players_html = ""
    if players:
        cells = ""
        for role, name, line in players:
            cells += (
                f'<tr><td style="padding:8px 0;border-bottom:1px solid {C_ROW_BORDER};">'
                f'<div style="{label_css}">{role}</div>'
                f'<div style="font-family:{FONT_EDITORIAL};font-size:15px;font-weight:700;color:#041e42;margin-top:2px;">{esc(name)}</div>'
                f'<div style="font-family:{FONT_DATA};font-size:12px;font-weight:600;color:{C_MID_BLUE};margin-top:2px;">{line}</div>'
                f"</td></tr>"
            )
        players_html = (
            f'<div style="{label_css}margin:16px 0 4px;">{opponent} players to watch</div>'
            f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">{cells}</table>'
        )
    facts_html = (
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">{rows}</table>'
        if rows
        else ""
    )
    return f"""
    <tr><td style="padding:14px 28px 18px 28px;">
      {facts_html}
      {players_html}
    </td></tr>"""


def next_game_schedule_line(notes: dict | None) -> str:
    """'Second game in two nights · game 2 of a 6-game road trip' — or ""."""
    if not notes:
        return ""
    parts = []
    if notes.get("next_is_back_to_back"):
        parts.append("second game in two nights")
    total = notes.get("total", 0)
    if total >= 2:
        kind = "road trip" if notes.get("run_type") == "road" else "homestand"
        size = f"{total}+" if notes.get("run_reaches_end") else str(total)
        parts.append(f"game {notes.get('position', 1)} of a {size}-game {kind}")
    if not parts:
        return ""
    parts[0] = parts[0][0].upper() + parts[0][1:]
    return " · ".join(parts)


def _build_next_game_html(
    next_game: dict,
    preview: dict | None = None,
    road_weather: dict | None = None,
    schedule_notes: dict | None = None,
) -> str:
    """Build the next game card with matchup, H2H stats, and players to watch.

    Args:
        next_game: The next_game dict from nhl.get_team_data().
        preview: Optional next_game_preview dict with H2H, opponent stats.
        road_weather: Optional weather dict from weather.fetch_road_game_weather().

    Returns:
        HTML string for the next game section.
    """
    if not next_game:
        return ""

    ng_date = _format_date(next_game.get("date", "")) or "TBD"
    ng_opponent = next_game.get("opponent", "TBD")
    ng_venue = "Home" if next_game.get("home_or_away") == "home" else "Away"

    # Marker: "Tonight" only on game day (local date); otherwise the game date's weekday
    ng_weekday = next_game.get("weekday", "")
    if next_game.get("is_today"):
        marker_label = "Next Up · Tonight"
    elif ng_weekday:
        marker_label = f"Next Up · {ng_weekday}"
    else:
        marker_label = "Next Up"

    opp_logo_url = f"https://assets.nhle.com/logos/nhl/svg/{ng_opponent}_light.svg"

    # Details line: full start string (display time zone) (falls back to the date) + venue
    venue_label = "vs" if ng_venue == "Home" else "@"
    game_time = next_game.get("time", "")
    game_venue_name = next_game.get("venue", "")
    details_parts = [p for p in [game_time or ng_date, esc(game_venue_name)] if p]
    details_str = " · ".join(details_parts)
    schedule_line = next_game_schedule_line(schedule_notes)
    schedule_html = (
        f'<div style="font-family:{FONT_DATA};font-size:13px;font-weight:700;color:{C_SECONDARY};margin-top:6px;">{schedule_line}</div>'
        if schedule_line
        else ""
    )

    preview_html = _build_next_game_preview_rows(preview or {}, ng_opponent)

    # Weather
    weather_html = ""
    if road_weather:
        city = esc(road_weather.get("city", ""))
        temp_c = road_weather.get("temp_c", "")
        description = esc(road_weather.get("description", ""))
        conditions = f"{temp_c}°C · {description}" if temp_c else description
        weather_html = f"""
    <tr><td style="padding:0 28px 24px 28px;">
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#f8f9fb;">
        <tr>
          <td style="padding:12px 14px;font-family:{FONT_DATA};font-size:12px;font-weight:700;color:#718096;letter-spacing:1.5px;text-transform:uppercase;">{city}</td>
          <td style="padding:12px 14px;font-family:{FONT_EDITORIAL};font-size:14px;font-weight:700;color:#191c1e;text-align:right;">{conditions}</td>
        </tr>
      </table>
    </td></tr>"""

    return f"""
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
           style="background:#ffffff;border-radius:12px;overflow:hidden;">
      <tr><td style="padding:28px 28px 8px 28px;">
        {_section_marker(marker_label)}
      </td></tr>
      <tr><td style="padding:18px 28px 8px 28px;">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
          <tr>
            <td valign="middle" width="62">
              <img src="{opp_logo_url}" width="54" alt="{ng_opponent}" style="display:block;width:54px;height:auto;border:0;outline:none;text-decoration:none;">
            </td>
            <td valign="middle" style="padding-left:14px;">
              <div style="font-family:{FONT_EDITORIAL};font-size:22px;font-weight:800;color:#191c1e;letter-spacing:-0.5px;line-height:1.1;">{venue_label} {ng_opponent}</div>
              <div style="font-family:{FONT_DATA};font-size:13px;font-weight:600;color:#4a5568;margin-top:4px;">{details_str}</div>
              {schedule_html}
            </td>
          </tr>
        </table>
      </td></tr>
      {preview_html}
      {weather_html}
    </table>
    """


def _second_of_back_to_back(upcoming_games: list) -> set[int]:
    """Indexes of games played the day after the game before them."""
    out = set()
    for i in range(1, len(upcoming_games)):
        try:
            prev = datetime.fromisoformat(upcoming_games[i - 1].get("date", "")[:10])
            cur = datetime.fromisoformat(upcoming_games[i].get("date", "")[:10])
        except ValueError:
            continue
        if (cur - prev).days == 1:
            out.add(i)
    return out


def _build_upcoming_schedule_html(upcoming_games: list) -> str:
    """Build the Coming Up section: the games after Next Up.

    Each row: start time (display time zone), opponent logo, "@"/"vs" and the opponent,
    and a B2B tag on the second game of a consecutive-day pair.

    Args:
        upcoming_games: All upcoming games from nhl.get_team_data(), Next Up
            first. The first is skipped here (Next Up shows it) but still counts
            for the back-to-back tag on the game after it.

    Returns:
        HTML string for the upcoming schedule, or empty string if empty.
    """
    if len(upcoming_games) < 2:
        return ""
    b2b = _second_of_back_to_back(upcoming_games)

    rows = ""
    for row, (i, g) in enumerate(list(enumerate(upcoming_games))[1:]):
        bg = C_SURFACE_LOW if row % 2 == 0 else C_SURFACE_LOWEST
        opp = g.get("opponent", "")
        if not opp:
            continue
        sign = "vs" if g.get("home_or_away") == "home" else "@"
        when = g.get("time") or _format_date(g.get("date", ""))
        tag = (
            f'<span style="display:inline-block;padding:2px 6px;background:{C_PRIMARY_CONT};border-radius:2px;font-size:10px;font-weight:700;letter-spacing:1px;color:#ffffff;">B2B</span>'
            if i in b2b
            else ""
        )
        opp_logo = f'<img src="{_team_logo_url(opp)}" width="24" alt="{opp}" style="display:block;border:0;max-width:24px;" />'
        rows += (
            f'<tr style="background:{bg};">'
            f'<td style="padding:7px 8px 7px 10px;font-size:12px;color:{C_ON_SURFACE_MED};">{when}</td>'
            f'<td style="padding:7px 4px;width:28px;">{opp_logo}</td>'
            f'<td style="padding:7px 4px;font-size:13px;font-weight:700;color:{C_ON_SURFACE};white-space:nowrap;">{sign}&nbsp;{opp}</td>'
            f'<td style="padding:7px 10px 7px 4px;text-align:right;white-space:nowrap;">{tag}</td>'
            f"</tr>"
        )

    return f"""
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
           style="background:#ffffff;border-radius:12px;overflow:hidden;">
      <tr><td style="padding:28px 28px 8px 28px;">
        {_section_marker("Coming Up")}
      </td></tr>
      <tr><td style="padding:8px 28px 26px 28px;">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
          {rows}
        </table>
      </td></tr>
    </table>
    """
