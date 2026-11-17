"""People cards: top scorers, player of the week and milestones, injuries, prospects."""

from datetime import datetime

from emailer.theme import (
    C_LOSS,
    C_MID_BLUE,
    C_ON_SURFACE,
    C_ON_SURFACE_MED,
    C_ON_SURFACE_MUTED,
    C_PRIMARY_CONT,
    C_ROW_BORDER,
    C_SECONDARY_CONT,
    C_SURFACE_LOW,
    C_SURFACE_LOWEST,
    C_WIN,
    FONT_DATA,
    FONT_EDITORIAL,
    _save_pct_display,
    _section_marker,
    esc,
)


def _build_top_scorers_html(top_scorers: list, is_playoffs: bool = False) -> str:
    """Build our team top scorers leaderboard table.

    Args:
        top_scorers: List of scorer dicts from nhl.get_team_data().
        is_playoffs: If True, label the section as playoff stats.

    Returns:
        HTML string for the top scorers section, or empty string if empty.
    """
    if not top_scorers:
        return ""

    section_label = "Playoff Leaders" if is_playoffs else "Team Leaders"
    rows = ""
    for i, p in enumerate(top_scorers):
        border = f"border-bottom:1px solid {C_ROW_BORDER};" if i < len(top_scorers) - 1 else ""
        rows += (
            f"<tr>"
            f'<td style="padding:11px 12px;{border}font-family:{FONT_DATA};font-size:14px;font-weight:600;color:#191c1e;">{esc(p["name"])}</td>'
            f'<td style="padding:11px 8px;{border}font-family:{FONT_EDITORIAL};font-size:13px;font-weight:700;color:#4a5568;text-align:center;">{p["goals"]}</td>'
            f'<td style="padding:11px 8px;{border}font-family:{FONT_EDITORIAL};font-size:13px;font-weight:700;color:#4a5568;text-align:center;">{p["assists"]}</td>'
            f'<td style="padding:11px 12px;{border}font-family:{FONT_EDITORIAL};font-size:14px;font-weight:800;color:#d53e00;text-align:right;">{p["points"]}</td>'
            f"</tr>"
        )

    return f"""
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
           style="background:#ffffff;border-radius:12px;overflow:hidden;">
      <tr><td style="padding:28px 28px 8px 28px;">
        {_section_marker(section_label)}
      </td></tr>
      <tr><td style="padding:14px 28px 24px 28px;">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
          <tr style="background:#f8f9fb;">
            <td style="padding:8px 12px;font-family:{FONT_DATA};font-size:10px;font-weight:700;color:#718096;letter-spacing:1.2px;text-transform:uppercase;">Player</td>
            <td style="padding:8px 8px;font-family:{FONT_DATA};font-size:10px;font-weight:700;color:#718096;letter-spacing:1.2px;text-transform:uppercase;text-align:center;">G</td>
            <td style="padding:8px 8px;font-family:{FONT_DATA};font-size:10px;font-weight:700;color:#718096;letter-spacing:1.2px;text-transform:uppercase;text-align:center;">A</td>
            <td style="padding:8px 12px;font-family:{FONT_DATA};font-size:10px;font-weight:700;color:#718096;letter-spacing:1.2px;text-transform:uppercase;text-align:right;">Pts</td>
          </tr>
          {rows}
        </table>
      </td></tr>
    </table>
    """


def _build_player_of_week_html(player_of_week: dict, milestones: list) -> str:
    """Build the player of the week callout and milestone watch section.

    Combines both in one card to avoid too many separate cards.

    Args:
        player_of_week: Dict from nhl.get_team_data(), or None.
        milestones: List of milestone dicts from nhl.get_team_data().

    Returns:
        HTML string for the combined card, or empty string if no data.
    """
    if not player_of_week and not milestones:
        return ""

    pow_html = ""
    if player_of_week:
        pow_html = (
            f'<p style="margin:0 0 6px;font-family:{FONT_DATA};font-size:11px;font-weight:700;'
            f'letter-spacing:2px;color:#718096;text-transform:uppercase;">Last 5 Games</p>'
            f'<p style="margin:0;font-size:16px;font-weight:800;color:{C_PRIMARY_CONT};font-family:{FONT_EDITORIAL};">'
            f"{esc(player_of_week['name'])}"
            f'<span style="font-size:14px;font-weight:400;color:{C_ON_SURFACE_MED};margin-left:10px;">'
            f"{player_of_week['goals']}G&nbsp;{player_of_week['assists']}A&nbsp;"
            f'<strong style="color:{C_SECONDARY_CONT};">{player_of_week["points"]}pts</strong>'
            f'&nbsp;<span style="color:{C_ON_SURFACE_MUTED};font-size:12px;">in {player_of_week["games"]} GP</span>'
            f"</span></p>"
        )

    ms_html = ""
    if milestones:
        items = ""
        for m in milestones:
            items += (
                f'<li style="margin:4px 0;font-size:13px;color:{C_ON_SURFACE_MED};">'
                f"<strong>{esc(m['name'])}</strong> — {m['needed']} {m['stat']} from "
                f'<strong style="color:{C_SECONDARY_CONT};">{m["next_milestone"]}</strong>'
                f" ({m['current']} now)"
                f"</li>"
            )
        ms_html = (
            f'<p style="margin:{("16px" if pow_html else "0")} 0 6px;font-family:{FONT_DATA};font-size:11px;font-weight:700;'
            f'letter-spacing:2px;color:#718096;text-transform:uppercase;">Milestone Watch</p>'
            f'<ul style="margin:0;padding-left:18px;">{items}</ul>'
        )

    return f"""
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
           style="background:#ffffff;border-radius:12px;overflow:hidden;">
      <tr><td style="padding:28px 28px 8px 28px;">
        {_section_marker("Player of the Week · Milestones" if milestones else "Player of the Week")}
      </td></tr>
      <tr><td style="padding:14px 28px 26px 28px;">
        {pow_html}
        {ms_html}
      </td></tr>
    </table>
    """


def _injury_status_words(status: str) -> str:
    """'Injured Reserve' → 'on injured reserve'; other ESPN statuses lower-cased."""
    s = (status or "").strip()
    if not s:
        return ""
    if s.lower() == "injured reserve":
        return "on injured reserve"
    return s.lower()


def _build_injury_section_html(injuries: list) -> str:
    """Build the Injury Report card: one compact line per player who is out.

    Name and position on each line. When every player has the same status it is
    said once ("All on injured reserve"); otherwise each line carries its own.
    The injury type and ESPN's expected return date show only when ESPN gives them.

    Args:
        injuries: List of dicts from nhl.fetch_team_injuries().

    Returns:
        HTML string for the card, or empty string if no injuries.
    """
    if not injuries:
        return ""

    statuses = {(e.get("status") or "").strip() for e in injuries}
    shared_status = statuses.pop() if len(statuses) == 1 else None
    summary = ""
    if shared_status:
        words = _injury_status_words(shared_status)
        summary = f"All {words}" if len(injuries) > 1 else words.capitalize()

    rows = ""
    for i, entry in enumerate(injuries):
        player = esc(entry.get("player", ""))
        if not player:
            continue
        position = entry.get("position", "")
        pos_html = (
            f' <span style="color:{C_ON_SURFACE_MUTED};font-weight:600;">{esc(position)}</span>'
            if position and position != "?"
            else ""
        )
        details = []
        if not shared_status and entry.get("status"):
            details.append(_injury_status_words(entry["status"]).capitalize())
        if entry.get("injury"):
            details.append(esc(entry["injury"]))
        expected = entry.get("expected_return", "")
        if expected and expected.upper() != "TBD":
            try:
                d = datetime.fromisoformat(expected[:10])
                when = f"{d:%b} {d.day}"
            except ValueError:
                when = expected
            details.append(f"expected back {when}")
        detail_html = (
            f'<div style="font-size:13px;font-weight:400;color:{C_ON_SURFACE_MED};margin-top:2px;">{" · ".join(details)}</div>'
            if details
            else ""
        )
        border = f"border-top:1px solid {C_ROW_BORDER};" if i else ""
        rows += (
            f'<tr><td style="padding:10px 0;{border}font-family:{FONT_DATA};font-size:14px;font-weight:600;color:#191c1e;">'
            f"{player}{pos_html}{detail_html}</td></tr>"
        )

    summary_html = (
        f'<p style="margin:0 0 6px;font-family:{FONT_DATA};font-size:13px;font-weight:600;color:{C_MID_BLUE};">{summary}</p>'
        if summary
        else ""
    )
    return f"""
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
           style="background:#ffffff;border-radius:12px;overflow:hidden;">
      <tr><td style="padding:28px 28px 8px 28px;">
        {_section_marker("Injury Report")}
      </td></tr>
      <tr><td style="padding:14px 28px 22px 28px;">
        {summary_html}
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
          {rows}
        </table>
      </td></tr>
    </table>
    """


def _build_prospects_section(prospects: list) -> str:
    """Build our team Prospects section showing current-season stats.

    Displays top 8 skaters by points and all goalies with their key metrics,
    in whatever league they're currently playing.

    Args:
        prospects: List of prospect dicts from nhl.get_prospects_data().

    Returns:
        HTML string for the section, or empty string if list is empty.
    """
    if not prospects:
        return ""

    skaters = [p for p in prospects if p.get("position") != "G"][:8]
    goalies = [p for p in prospects if p.get("position") == "G"]

    if not skaters and not goalies:
        return ""

    # Skater rows
    skater_rows = ""
    for i, p in enumerate(skaters):
        bg = C_SURFACE_LOW if i % 2 == 0 else C_SURFACE_LOWEST
        league = p.get("league", "")
        team = p.get("team", "")
        league_team = esc(f"{league} · {team}" if team else league)
        pm = p.get("plus_minus", 0)
        pm_str = f"+{pm}" if pm > 0 else str(pm)
        pm_color = C_WIN if pm > 0 else (C_LOSS if pm < 0 else C_ON_SURFACE_MUTED)

        skater_rows += (
            f'<tr style="background:{bg};">'
            f'<td style="padding:7px 10px;font-size:13px;font-weight:700;color:{C_ON_SURFACE};word-break:break-word;">'
            f"{esc(p['name'])}"
            f'<span style="font-size:11px;font-weight:400;color:{C_ON_SURFACE_MUTED};margin-left:5px;">'
            f"{esc(p.get('position', ''))}</span></td>"
            f'<td style="padding:7px 6px;font-size:11px;color:{C_ON_SURFACE_MED};word-break:break-word;">{league_team}</td>'
            f'<td style="padding:7px 4px;font-size:12px;color:{C_ON_SURFACE_MED};text-align:right;">{p.get("gp", 0)}</td>'
            f'<td style="padding:7px 4px;font-size:12px;color:{C_ON_SURFACE_MED};text-align:right;">{p.get("goals", 0)}</td>'
            f'<td style="padding:7px 4px;font-size:12px;color:{C_ON_SURFACE_MED};text-align:right;">{p.get("assists", 0)}</td>'
            f'<td style="padding:7px 4px;font-size:13px;font-weight:700;color:{C_ON_SURFACE};text-align:right;">{p.get("points", 0)}</td>'
            f'<td style="padding:7px 10px 7px 4px;font-size:12px;font-weight:600;color:{pm_color};text-align:right;">{pm_str}</td>'
            f"</tr>"
        )

    skater_table = (
        f"""
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
             style="margin-bottom:8px;">
        <tr style="background:{C_PRIMARY_CONT};">
          <th style="padding:5px 10px;font-size:11px;font-weight:600;color:#a8bcd8;text-align:left;">Player</th>
          <th style="padding:5px 6px;font-size:11px;font-weight:600;color:#a8bcd8;text-align:left;">League</th>
          <th style="padding:5px 4px;font-size:11px;font-weight:600;color:#a8bcd8;text-align:right;">GP</th>
          <th style="padding:5px 4px;font-size:11px;font-weight:600;color:#a8bcd8;text-align:right;">G</th>
          <th style="padding:5px 4px;font-size:11px;font-weight:600;color:#a8bcd8;text-align:right;">A</th>
          <th style="padding:5px 4px;font-size:11px;font-weight:600;color:#a8bcd8;text-align:right;">PTS</th>
          <th style="padding:5px 10px 5px 4px;font-size:11px;font-weight:600;color:#a8bcd8;text-align:right;">+/-</th>
        </tr>
        {skater_rows}
      </table>"""
        if skaters
        else ""
    )

    # Goalie rows
    goalie_rows = ""
    for i, p in enumerate(goalies):
        bg = C_SURFACE_LOW if i % 2 == 0 else C_SURFACE_LOWEST
        league = p.get("league", "")
        team = p.get("team", "")
        league_team = esc(f"{league} · {team}" if team else league)
        gp = p.get("gp", 0)
        sv_pct = p.get("sv_pct", 0.0)
        gaa = p.get("gaa", 0.0)

        if gp == 0:
            sv_display = "—"
            gaa_display = "—"
            wins_display = "—"
            league_team = league_team or "No games played"
        else:
            sv_display = _save_pct_display(sv_pct)
            gaa_display = f"{gaa:.2f}"
            wins_display = str(p.get("wins", 0))

        goalie_rows += (
            f'<tr style="background:{bg};">'
            f'<td style="padding:7px 10px;font-size:13px;font-weight:700;color:{C_ON_SURFACE};word-break:break-word;">'
            f"{esc(p['name'])}"
            f'<span style="font-size:11px;font-weight:400;color:{C_ON_SURFACE_MUTED};margin-left:5px;">G</span></td>'
            f'<td style="padding:7px 6px;font-size:11px;color:{C_ON_SURFACE_MED};word-break:break-word;">{league_team}</td>'
            f'<td style="padding:7px 4px;font-size:12px;color:{C_ON_SURFACE_MED};text-align:right;">{gp}</td>'
            f'<td style="padding:7px 4px;font-size:12px;color:{C_ON_SURFACE_MED};text-align:right;">{wins_display}</td>'
            f'<td style="padding:7px 4px;font-size:12px;color:{C_ON_SURFACE_MED};text-align:right;">{gaa_display}</td>'
            f'<td style="padding:7px 10px 7px 4px;font-size:13px;font-weight:700;'
            f'color:{C_ON_SURFACE};text-align:right;">{sv_display}</td>'
            f"</tr>"
        )

    goalie_table = (
        f"""
      <p style="margin:12px 0 6px;font-size:11px;font-weight:600;letter-spacing:1px;
                color:{C_ON_SURFACE_MUTED};text-transform:uppercase;">Goalies</p>
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
        <tr style="background:{C_PRIMARY_CONT};">
          <th style="padding:5px 10px;font-size:11px;font-weight:600;color:#a8bcd8;text-align:left;">Player</th>
          <th style="padding:5px 6px;font-size:11px;font-weight:600;color:#a8bcd8;text-align:left;">League</th>
          <th style="padding:5px 4px;font-size:11px;font-weight:600;color:#a8bcd8;text-align:right;">GP</th>
          <th style="padding:5px 4px;font-size:11px;font-weight:600;color:#a8bcd8;text-align:right;">W</th>
          <th style="padding:5px 4px;font-size:11px;font-weight:600;color:#a8bcd8;text-align:right;">GAA</th>
          <th style="padding:5px 10px 5px 4px;font-size:11px;font-weight:600;color:#a8bcd8;text-align:right;">SV%</th>
        </tr>
        {goalie_rows}
      </table>"""
        if goalies
        else ""
    )

    return f"""
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
           style="background:#ffffff;border-radius:12px;overflow:hidden;">
      <tr><td style="padding:28px 28px 8px 28px;">
        {_section_marker("Prospects")}
      </td></tr>
      <tr><td style="padding:14px 28px 26px 28px;">
        {skater_table}
        {goalie_table}
      </td></tr>
    </table>"""
