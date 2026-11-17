"""Last game cards: score card, goal log and three stars."""

from emailer.theme import (
    ABBR,
    C_MID_BLUE,
    C_ON_SECONDARY,
    C_ON_SURFACE_MED,
    C_OTL,
    C_SURFACE_LOW,
    FONT_DATA,
    FONT_EDITORIAL,
    RESULT_COLORS,
    _format_date,
    _result_label,
    _section_marker,
    esc,
)
from nhl import goalie_game_line


def _build_last_game_html(last_game: dict, advanced_stats: dict | None = None) -> str:
    """Build the last game card section: score, team stats grid, and goalies.

    Args:
        last_game: The last_game dict from nhl.get_team_data().
        advanced_stats: Optional advanced stats dict.

    Returns:
        HTML string for the last game section.
    """
    if not last_game:
        return f"""
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
               style="background:#ffffff;border-radius:12px;overflow:hidden;">
          <tr><td style="padding:28px;">
            <p style="margin:0;font-size:16px;color:{C_ON_SURFACE_MED};">No recently completed game found.</p>
          </td></tr>
        </table>
        """

    result = last_game.get("result", "?")
    result_color = RESULT_COLORS.get(result, C_OTL)
    result_label = _result_label(result)
    our_score = last_game.get("our_score", 0)
    opp_score = last_game.get("opponent_score", 0)
    opponent = last_game.get("opponent", "")
    period_type = (last_game.get("period_type") or "REG").upper()
    # Only mark games that went past regulation
    period_label = period_type if period_type in ("OT", "SO") else ""

    # --- Team stats comparison grid ---
    team_stats = last_game.get("team_stats", {})
    our_ts = team_stats.get("ours", {})
    opp_ts = team_stats.get("opponent", {})

    # Power play as goals/opportunities when the right-rail stats provide it
    if our_ts.get("power_play") and opp_ts.get("power_play"):
        pp_row = ("Power Play", our_ts["power_play"], opp_ts["power_play"])
    else:
        pp_row = ("PP Goals", our_ts.get("pp_goals"), opp_ts.get("pp_goals"))
    stat_rows_data = [
        ("Shots", our_ts.get("sog"), opp_ts.get("sog")),
        ("Hits", our_ts.get("hits"), opp_ts.get("hits")),
        ("Faceoffs", our_ts.get("faceoffs"), opp_ts.get("faceoffs")),
        pp_row,
        ("PIM", our_ts.get("pim"), opp_ts.get("pim")),
        ("Blocks", our_ts.get("blocked"), opp_ts.get("blocked")),
    ]
    # Skip any row the API didn't fill — never render a row of dashes
    stat_rows_data = [
        (label, a, b)
        for label, a, b in stat_rows_data
        if a not in (None, "", "—") and b not in (None, "", "—")
    ]

    stat_rows_html = ""
    for i, (label, our_val, opp_val) in enumerate(stat_rows_data):
        bg = "#ffffff" if i % 2 == 0 else C_SURFACE_LOW
        stat_rows_html += (
            f'<tr style="background:{bg};">'
            f'<td style="padding:10px 12px;color:#041e42;font-size:14px;font-weight:700;width:25%;">{our_val}</td>'
            f'<td style="padding:10px 12px;color:{C_MID_BLUE};font-size:11px;font-weight:600;letter-spacing:1.5px;text-transform:uppercase;text-align:center;">{label}</td>'
            f'<td style="padding:10px 12px;color:{C_MID_BLUE};font-size:14px;font-weight:700;width:25%;text-align:right;">{opp_val}</td>'
            f"</tr>"
        )

    # --- Goalies: Our goalie(s) and the opponent's starter, side by side ---
    our_goalies = list(last_game.get("goalies", []))
    opp_goalie = last_game.get("opponent_goalie")

    def _goalie_cell(g: dict, team: str, conceded: int, bg: str) -> str:
        dec = g.get("decision", "")
        dec_label = {"W": "Win", "L": "Loss", "O": "OT Loss"}.get(dec, dec)
        label = f"{team} · {dec_label}" if dec_label else team
        saves, shots = g.get("saves", 0), g.get("shots_against", 0)
        line = goalie_game_line(saves, shots, conceded == 0 and saves == shots)
        return (
            f'<td width="50%" valign="top" style="padding:14px;background:{bg};">'
            f'<div style="font-family:{FONT_DATA};font-size:10px;font-weight:700;letter-spacing:1.5px;color:{C_MID_BLUE};text-transform:uppercase;">{label}</div>'
            f'<div style="font-family:{FONT_EDITORIAL};font-size:16px;font-weight:700;color:#041e42;margin-top:4px;letter-spacing:-0.3px;">{esc(g.get("name", ""))}</div>'
            f'<div style="font-family:{FONT_EDITORIAL};font-size:13px;font-weight:600;color:{C_MID_BLUE};margin-top:6px;">{line}</div>'
            f"</td>"
        )

    goalie_cells = ""
    for g in our_goalies:
        goalie_cells += _goalie_cell(g, f"{ABBR}", opp_score, C_SURFACE_LOW)
    if opp_goalie:
        goalie_cells += _goalie_cell(opp_goalie, opponent, our_score, "#ffffff")

    # --- Game date + venue (row omitted when there's nothing to show) ---
    date_str = last_game.get("date", "")
    weekday = last_game.get("weekday", "")
    date_display = _format_date(date_str) if date_str else ""
    if date_display and weekday:
        date_display = f"{weekday}, {date_display}"
    venue_parts = [
        esc(p) for p in [last_game.get("venue", ""), last_game.get("venue_city", "")] if p
    ]
    info_parts = [p for p in [date_display, ", ".join(venue_parts)] if p]
    info_row_html = ""
    if info_parts:
        info_row_html = f"""
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="margin-top:14px;">
          <tr><td style="border-top:1px solid #e6eaf0;padding-top:12px;font-family:{FONT_DATA};font-size:12px;font-weight:600;color:{C_MID_BLUE};letter-spacing:0.5px;">
            {" &middot; ".join(info_parts)}
          </td></tr>
        </table>"""
    # Under the badge: OT / SO when it went past regulation, SHUTOUT for a shutout win
    # (never "SO" for a shutout — SO means shootout)
    under_badge = [period_label] if period_label else []
    if result == "W" and opp_score == 0:
        under_badge.append("Shutout")
    period_html = "".join(
        f'<div style="font-family:{FONT_DATA};font-size:11px;font-weight:700;color:{C_MID_BLUE};margin-top:10px;letter-spacing:1px;text-transform:uppercase;">{text}</div>'
        for text in under_badge
    )

    # --- Recap link ---
    recap_link = last_game.get("recap_link")
    recap_html = ""
    if recap_link:
        recap_html = f"""
    <tr><td style="padding:0 28px 30px 28px;" align="center">
      <table role="presentation" cellpadding="0" cellspacing="0" border="0"><tr><td style="background:#d53e00;border-radius:4px;">
        <a href="{esc(recap_link)}" style="display:block;padding:14px 26px;font-family:{FONT_DATA};font-size:13px;font-weight:700;color:{C_ON_SECONDARY};text-decoration:none;letter-spacing:1.5px;text-transform:uppercase;">View Full Recap →</a>
      </td></tr></table>
    </td></tr>"""

    opp_logo_url = f"https://assets.nhle.com/logos/nhl/svg/{opponent}_light.svg"

    return f"""
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
           style="background:#ffffff;border-radius:0 0 12px 12px;overflow:hidden;">
      <tr><td style="padding:28px 28px 4px 28px;">
        {_section_marker("Last Game · Final")}
      </td></tr>

      <tr><td style="padding:18px 28px 22px 28px;">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
          <tr>
            <td valign="middle" width="42%">
              <img src="https://assets.nhle.com/logos/nhl/svg/{ABBR}_light.svg" width="44" alt="{ABBR}" style="display:block;width:44px;height:auto;border:0;outline:none;text-decoration:none;margin-bottom:8px;">
              <div style="font-family:{FONT_DATA};font-size:12px;font-weight:700;letter-spacing:2px;color:{C_MID_BLUE};text-transform:uppercase;">{ABBR}</div>
              <div style="font-family:{FONT_EDITORIAL};font-size:64px;font-weight:800;color:#041e42;line-height:1;letter-spacing:-2px;margin-top:4px;">{our_score}</div>
            </td>
            <td valign="middle" width="16%" align="center">
              <div style="display:inline-block;padding:6px 12px;background:{result_color};border-radius:3px;font-family:{FONT_DATA};font-size:11px;font-weight:700;letter-spacing:2px;color:#ffffff;text-transform:uppercase;">{result_label}</div>
              {period_html}
            </td>
            <td valign="middle" width="42%" align="right">
              <img src="{opp_logo_url}" width="44" alt="{opponent}" style="display:block;width:44px;height:auto;border:0;outline:none;text-decoration:none;margin-bottom:8px;margin-left:auto;">
              <div style="font-family:{FONT_DATA};font-size:12px;font-weight:700;letter-spacing:2px;color:{C_MID_BLUE};text-transform:uppercase;">{opponent}</div>
              <div style="font-family:{FONT_EDITORIAL};font-size:64px;font-weight:800;color:{C_MID_BLUE};line-height:1;letter-spacing:-2px;margin-top:4px;">{opp_score}</div>
            </td>
          </tr>
        </table>
        {info_row_html}
      </td></tr>

      <tr><td style="padding:0 28px 22px 28px;">
        <div style="font-family:{FONT_DATA};font-size:10px;font-weight:700;letter-spacing:2px;color:{C_MID_BLUE};text-transform:uppercase;margin-bottom:10px;">Team Stats</div>
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="font-family:{FONT_DATA};">
          {stat_rows_html}
        </table>
      </td></tr>

      <tr><td style="padding:0 28px 22px 28px;">
        <div style="font-family:{FONT_DATA};font-size:10px;font-weight:700;letter-spacing:2px;color:{C_MID_BLUE};text-transform:uppercase;margin-bottom:10px;">Goaltending</div>
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
          <tr>{goalie_cells}</tr>
        </table>
      </td></tr>

      {recap_html}
    </table>
    """


def _build_scoring_summary_html(last_game: dict) -> str:
    """Build the goal log section showing every goal by period.

    Args:
        last_game: The last_game dict from nhl.get_team_data().

    Returns:
        HTML string for the scoring summary, or empty string if no data.
    """
    scoring = last_game.get("scoring_summary", []) if last_game else []
    if not scoring:
        return ""

    periods_html = ""
    period_count = 0
    our_running = 0
    opp_running = 0
    for period in scoring:
        goals = period.get("goals", [])
        if not goals:
            continue

        period_label = period.get("period_label", "")
        period_name = f"{period_label} Period" if period_label else "Period"

        # Add border-top to 2nd and 3rd period headers
        border_top = "border-top:1px solid #eceef2;" if period_count > 0 else ""

        period_header = (
            f'<tr><td style="padding:{"14px" if period_count > 0 else "18px"} 28px 8px 28px;{border_top}">'
            f'<div style="font-family:{FONT_EDITORIAL};font-size:13px;font-weight:700;color:#041e42;letter-spacing:1px;text-transform:uppercase;">{period_name}</div>'
            f"</td></tr>"
        )

        goal_rows = ""
        for gi, g in enumerate(goals):
            team = g.get("team", "")
            is_us = team == ABBR

            # Update running score
            if is_us:
                our_running += 1
            else:
                opp_running += 1

            assists = g.get("assists", [])
            strength = g.get("strength", "EV")

            # Strength badge
            badge_html = ""
            if strength == "PP":
                badge_html = (
                    '<span style="display:inline-block;padding:1px 5px;background:#fbe9e3;'
                    "color:#aa3000;font-size:9px;font-weight:700;letter-spacing:1px;border-radius:2px;"
                    'vertical-align:1px;">PP</span>'
                )
            elif strength == "EN":
                badge_html = (
                    '<span style="display:inline-block;padding:1px 5px;background:#e8edf3;'
                    "color:#4a5568;font-size:9px;font-weight:700;letter-spacing:1px;border-radius:2px;"
                    'vertical-align:1px;">EN</span>'
                )
            elif strength not in ("EV", ""):
                badge_html = (
                    f'<span style="display:inline-block;padding:1px 5px;background:#e8edf3;'
                    f"color:#4a5568;font-size:9px;font-weight:700;letter-spacing:1px;border-radius:2px;"
                    f'vertical-align:1px;">{strength}</span>'
                )

            assist_str = ""
            if assists:
                assist_str = f'<div style="font-family:{FONT_DATA};font-size:12px;color:#718096;margin-top:2px;">Assists: {", ".join(esc(a) for a in assists)}'
                if strength == "EV" or strength == "":
                    assist_str += " · EV"
                assist_str += "</div>"
            else:
                assist_str = f'<div style="font-family:{FONT_DATA};font-size:12px;color:#718096;margin-top:2px;">Unassisted</div>'

            # Scoreline: EDM score left, opponent right; scorer's side is bold
            if is_us:
                score_left_color = "#191c1e"
                score_right_color = "#8a93a8"
            else:
                score_left_color = "#8a93a8"
                score_right_color = "#191c1e"

            divider_row = ""
            if gi > 0:
                divider_row = '<tr><td colspan="3" style="border-top:1px solid #eceef2;line-height:0;font-size:0;">&nbsp;</td></tr>'

            logo_url = f"https://assets.nhle.com/logos/nhl/svg/{team}_light.svg"
            team_logo_img = (
                f'<img src="{logo_url}" width="20" alt="{team}" '
                f'style="display:inline-block;width:20px;height:auto;vertical-align:middle;'
                f'border:0;margin-right:6px;">'
            )

            goal_rows += (
                f"{divider_row}"
                f"<tr>"
                f'<td width="48" valign="top" style="font-family:{FONT_EDITORIAL};font-size:13px;font-weight:700;color:#718096;padding:10px 0;">{g.get("time", "")}</td>'
                f'<td valign="top" style="padding:10px 12px 10px 0;">'
                f'<div style="font-family:{FONT_DATA};font-size:14px;font-weight:600;color:#191c1e;line-height:1.3;">'
                f"{team_logo_img}"
                f"{esc(g.get('scorer', ''))} {badge_html}</div>"
                f"{assist_str}"
                f"</td>"
                f'<td valign="top" align="right" style="font-family:{FONT_EDITORIAL};font-size:13px;font-weight:700;padding:10px 0;white-space:nowrap;">'
                f'<span style="color:{score_left_color};">{our_running}</span>'
                f'<span style="color:#cbd2dc;">–</span>'
                f'<span style="color:{score_right_color};">{opp_running}</span>'
                f"</td>"
                f"</tr>"
            )

        periods_html += f"""
    {period_header}
    <tr><td style="padding:0 28px 8px 28px;">
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
        {goal_rows}
      </table>
    </td></tr>"""
        period_count += 1

    if not periods_html:
        return ""

    return f"""
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
           style="background:#ffffff;border-radius:12px;overflow:hidden;">
      <tr><td style="padding:28px 28px 4px 28px;">
        {_section_marker("Goal Log")}
      </td></tr>
      {periods_html}
    </table>
    """


def _build_three_stars_html(last_game: dict) -> str:
    """Build the Three Stars section for the last game.

    Args:
        last_game: The last_game dict from nhl.get_team_data().

    Returns:
        HTML string for the three stars section, or empty string if no data.
    """
    stars = last_game.get("three_stars", []) if last_game else []
    if not stars:
        return ""

    STAR_NUM_COLORS = ["#d53e00", "#aa3000", "#718096"]
    STAR_TOP_BORDERS = [
        "border-top:3px solid #d53e00;",
        "border-top:3px solid #aa3000;",
        "border-top:3px solid #cbd2dc;",
    ]
    STAR_PADDINGS = ["padding-right:8px;", "padding:0 4px;", "padding-left:8px;"]

    cols = ""
    for i, s in enumerate(stars[:3]):
        num_color = STAR_NUM_COLORS[i] if i < len(STAR_NUM_COLORS) else "#718096"
        top_border = STAR_TOP_BORDERS[i] if i < len(STAR_TOP_BORDERS) else ""
        pad = STAR_PADDINGS[i] if i < len(STAR_PADDINGS) else ""
        team = s.get("team", "")
        summary = s.get("summary", "")
        pos = s.get("position", "")
        team_pos = " · ".join(p for p in [team, pos] if p)

        team_logo_html = ""
        if team:
            team_logo_html = (
                f'<img src="https://assets.nhle.com/logos/nhl/svg/{team}_light.svg" '
                f'width="32" alt="{team}" style="display:block;width:32px;height:auto;'
                f'border:0;outline:none;text-decoration:none;margin-bottom:8px;">'
            )

        cols += (
            f'<td width="33%" valign="top" style="{pad}">'
            f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#f8f9fb;{top_border}">'
            f'<tr><td style="padding:14px 12px;">'
            f"{team_logo_html}"
            f'<div style="font-family:{FONT_EDITORIAL};font-size:24px;font-weight:800;color:{num_color};line-height:1;letter-spacing:-1px;">'
            f'{i + 1}<span style="font-size:12px;vertical-align:6px;">★</span></div>'
            f'<div style="font-family:{FONT_DATA};font-size:13px;font-weight:700;color:#191c1e;margin-top:8px;line-height:1.2;">{esc(s.get("name", ""))}</div>'
            f'<div style="font-family:{FONT_DATA};font-size:11px;color:#718096;margin-top:2px;">{team_pos}</div>'
            f'<div style="font-family:{FONT_EDITORIAL};font-size:12px;font-weight:700;color:#041e42;margin-top:8px;">{esc(summary)}</div>'
            f"</td></tr>"
            f"</table>"
            f"</td>"
        )

    return f"""
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
           style="background:#ffffff;border-radius:12px;overflow:hidden;">
      <tr><td style="padding:28px 28px 8px 28px;">
        {_section_marker("Three Stars")}
      </td></tr>
      <tr><td style="padding:18px 28px 24px 28px;">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
          <tr>{cols}</tr>
        </table>
      </td></tr>
    </table>
    """
