"""Standings cards: Western Conference standings, playoff race, magic number."""

from emailer.theme import (
    ABBR,
    C_ON_SURFACE,
    C_ON_SURFACE_MED,
    C_ON_SURFACE_MUTED,
    C_ROW_BORDER,
    C_SECONDARY_CONT,
    C_SURFACE_LOW,
    C_SURFACE_LOWEST,
    C_TEAM_HIGHLIGHT,
    CONF,
    CONF_SHORT,
    FONT_DATA,
    FONT_EDITORIAL,
    _section_marker,
    _team_logo_url,
    divisions_ours_first,
    esc,
)
from nhl import MAGIC_NUMBER_MIN_GP


def _build_conference_standings_html(conference_standings: dict) -> str:
    """Build our conference's standings table section.

    Laid out in NHL playoff format: top 3 of each division, the two wild
    cards, a playoff line, then the rest in wild card order. Our row is
    highlighted with an orange left accent.

    Args:
        conference_standings: Dict keyed by division name, our division first,
            from nhl._extract_conference_standings().

    Returns:
        HTML string for the standings section, or empty string if no data.
    """
    if not conference_standings:
        return ""

    # NHL format: top 3 in each division + 2 wild cards (best of the rest, conference-wide).
    everyone = [t for teams in conference_standings.values() for t in teams]
    others = sorted(
        (t for t in everyone if t.get("div_rank", 99) > 3),
        key=lambda t: t.get("wc_rank", 99),
    )
    # Seeds: first letter of the division ("P1" Pacific, "M2" Metropolitan, ...)
    groups = [
        (
            div_name,
            [
                (f"{div_name[0]}{t['div_rank']}", t, True)
                for t in teams
                if t.get("div_rank", 99) <= 3
            ],
        )
        for div_name, teams in divisions_ours_first(conference_standings)
    ]
    groups += [
        ("Wild Card", [(f"WC{i}", t, True) for i, t in enumerate(others[:2], 1)]),
        (None, [("", t, False) for t in others[2:]]),
    ]

    def _group_row(label: str, playoff_line: bool = False) -> str:
        text = "— Playoff line —" if playoff_line else label
        bg = "#f8f9fb" if playoff_line else "#ffffff"
        align = "center" if playoff_line else "left"
        return (
            f'<tr><td colspan="5" style="padding:12px 10px 6px;text-align:{align};background:{bg};'
            f"font-family:{FONT_DATA};font-size:10px;font-weight:700;color:#718096;"
            f'letter-spacing:1.2px;text-transform:uppercase;">{text}</td></tr>'
        )

    def _team_row(seed: str, team: dict, in_playoffs: bool) -> str:
        record = f"{team['wins']}-{team['losses']}-{team['ot_losses']}"
        name = esc(team.get("name", team.get("abbrev", "")))
        border = f"border-bottom:1px solid {C_ROW_BORDER};"
        if team.get("is_us"):
            row_style, pad = f' style="background:{C_TEAM_HIGHLIGHT};"', "11px"
            seed_css = "color:#d53e00;font-weight:800;border-left:3px solid #d53e00;"
            name_css, num_css, pts_css = (
                "color:#191c1e;font-weight:700;",
                "color:#191c1e;font-weight:700;",
                "color:#d53e00;font-weight:800;",
            )
        elif in_playoffs:
            row_style, pad = "", "9px"
            seed_css = "color:#191c1e;font-weight:700;"
            name_css, num_css, pts_css = (
                "color:#191c1e;font-weight:600;",
                "color:#4a5568;font-weight:600;",
                "color:#191c1e;font-weight:700;",
            )
        else:
            row_style, pad = "", "9px"
            seed_css = "color:#718096;font-weight:700;"
            name_css, num_css, pts_css = (
                "color:#4a5568;font-weight:600;",
                "color:#718096;font-weight:600;",
                "color:#4a5568;font-weight:700;",
            )
        return (
            f"<tr{row_style}>"
            f'<td style="padding:{pad} 10px;font-family:{FONT_EDITORIAL};font-size:12px;white-space:nowrap;{seed_css}{border}">{seed}</td>'
            f'<td style="padding:{pad} 10px;font-family:{FONT_DATA};font-size:13px;{name_css}{border}">{name}</td>'
            f'<td style="padding:{pad} 6px;font-family:{FONT_EDITORIAL};font-size:13px;text-align:center;{num_css}{border}">{team["gp"]}</td>'
            f'<td style="padding:{pad} 6px;font-family:{FONT_EDITORIAL};font-size:13px;text-align:center;white-space:nowrap;{num_css}{border}">{record}</td>'
            f'<td style="padding:{pad} 10px;font-family:{FONT_EDITORIAL};font-size:13px;text-align:right;{pts_css}{border}">{team["points"]}</td>'
            f"</tr>"
        )

    rows_html = ""
    for label, members in groups:
        if not members:
            continue
        rows_html += _group_row("", playoff_line=True) if label is None else _group_row(label)
        rows_html += "".join(_team_row(*m) for m in members)

    return f"""
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
           style="background:#ffffff;border-radius:12px;overflow:hidden;">
      <tr><td style="padding:28px 28px 8px 28px;">
        {_section_marker(f"{CONF} Conference")}
      </td></tr>
      <tr><td style="padding:14px 28px 14px 28px;">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
          <tr style="background:#f8f9fb;">
            <td style="padding:8px 10px;font-family:{FONT_DATA};font-size:10px;font-weight:700;color:#718096;letter-spacing:1.2px;text-transform:uppercase;width:34px;">Seed</td>
            <td style="padding:8px 10px;font-family:{FONT_DATA};font-size:10px;font-weight:700;color:#718096;letter-spacing:1.2px;text-transform:uppercase;">Team</td>
            <td style="padding:8px 6px;font-family:{FONT_DATA};font-size:10px;font-weight:700;color:#718096;letter-spacing:1.2px;text-transform:uppercase;text-align:center;">GP</td>
            <td style="padding:8px 6px;font-family:{FONT_DATA};font-size:10px;font-weight:700;color:#718096;letter-spacing:1.2px;text-transform:uppercase;text-align:center;">W-L-OT</td>
            <td style="padding:8px 10px;font-family:{FONT_DATA};font-size:10px;font-weight:700;color:#718096;letter-spacing:1.2px;text-transform:uppercase;text-align:right;">Pts</td>
          </tr>
          {rows_html}
        </table>
      </td></tr>
    </table>
    """


def _build_playoff_race_section(data: dict) -> str:
    """Build the playoff race section: the race table (sorted by points) and AI analysis.

    Only renders during the regular season and before we have clinched.

    Args:
        data: Structured data dict from nhl.get_team_data(), including
              the optional "playoff_race_analysis" key set by the scheduler.

    Returns:
        HTML string for the section, or empty string if not applicable.
    """
    playoff_race = data.get("playoff_race")
    playoff_bracket = data.get("playoff_bracket")

    if not playoff_race or playoff_bracket or playoff_race.get("clinched"):
        return ""
    if playoff_race.get("our_gp", 0) < MAGIC_NUMBER_MIN_GP:
        return ""  # too early in the season for a race table

    bubble_teams = playoff_race.get("bubble_teams", [])
    if not bubble_teams:
        return ""

    analysis = data.get("playoff_race_analysis", "")
    # Drop the Tonight column when none of the listed teams plays tonight
    show_tonight = any(t.get("tonight_opponent") for t in bubble_teams)

    rows = ""
    for i, t in enumerate(bubble_teams):
        bg = C_SURFACE_LOW if i % 2 == 0 else C_SURFACE_LOWEST
        abbrev = t["abbrev"]
        tonight = t.get("tonight_opponent") or "—"
        tonight_cell = (
            f'<td style="padding:6px 10px 6px 4px;font-size:11px;color:{C_ON_SURFACE_MUTED};text-align:right;">'
            f"{tonight}</td>"
            if show_tonight
            else ""
        )
        logo = (
            f'<img src="{_team_logo_url(abbrev)}" '
            f'width="20" alt="{abbrev}" style="display:block;border:0;max-width:20px;" />'
        )
        rows += (
            f'<tr style="background:{bg};">'
            f'<td style="padding:6px 6px 6px 10px;width:26px;">{logo}</td>'
            f'<td style="padding:6px 4px;font-size:12px;font-weight:600;color:{C_ON_SURFACE};">{abbrev}</td>'
            f'<td style="padding:6px 4px;font-size:12px;color:{C_ON_SURFACE_MED};text-align:right;">'
            f"<strong>{t['points']}</strong></td>"
            f'<td style="padding:6px 4px;font-size:12px;color:{C_ON_SURFACE_MUTED};text-align:right;">'
            f"{t['games_remaining']}</td>"
            f"{tonight_cell}"
            f"</tr>"
        )

    analysis_html = ""
    if analysis:
        escaped = esc(analysis)
        escaped = (
            escaped.replace("\n•", "<br>&bull;").replace("\n-", "<br>&ndash;").replace("\n", "<br>")
        )
        analysis_html = (
            f'<p style="margin:12px 0 0;font-size:14px;color:{C_ON_SURFACE_MED};line-height:1.6;">'
            f"{escaped}</p>"
        )

    tonight_header = (
        f'<th style="padding:7px 10px 7px 4px;font-family:{FONT_DATA};font-size:10px;font-weight:700;'
        f'letter-spacing:1.5px;color:#718096;text-align:right;text-transform:uppercase;">Tonight</th>'
        if show_tonight
        else ""
    )
    our_pts = playoff_race.get("our_points", "?")
    our_gr = playoff_race.get("our_games_remaining", "?")
    our_rank = playoff_race.get("our_rank", "?")

    return f"""
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
           style="background:#ffffff;border-radius:12px;overflow:hidden;">
      <tr><td style="padding:28px 28px 8px 28px;">
        {_section_marker("Playoff Race")}
      </td></tr>
      <tr><td style="padding:8px 28px 26px 28px;">
        <p style="margin:0 0 12px;font-size:13px;font-family:{FONT_DATA};color:{C_ON_SURFACE_MED};">
          {ABBR}: <strong style="color:{C_SECONDARY_CONT};font-size:15px;">{our_pts}</strong> pts
          &nbsp;&middot;&nbsp;#{our_rank} {CONF_SHORT}
          &nbsp;&middot;&nbsp;{our_gr} games left
        </p>
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
               style="margin-bottom:4px;">
          <tr style="background:#f8f9fb;">
            <th colspan="2" style="padding:7px 10px;font-family:{FONT_DATA};font-size:10px;font-weight:700;
                                   letter-spacing:1.5px;color:#718096;text-align:left;text-transform:uppercase;">Team</th>
            <th style="padding:7px 4px;font-family:{FONT_DATA};font-size:10px;font-weight:700;
                       letter-spacing:1.5px;color:#718096;text-align:right;text-transform:uppercase;">PTS</th>
            <th style="padding:7px 4px;font-family:{FONT_DATA};font-size:10px;font-weight:700;
                       letter-spacing:1.5px;color:#718096;text-align:right;text-transform:uppercase;">Left</th>
            {tonight_header}
          </tr>
          {rows}
        </table>
        {analysis_html}
      </td></tr>
    </table>"""


def _build_magic_number_html(magic_number, standings: dict, clinched_override: bool = False) -> str:
    """Build the magic number / playoff clinch callout line.

    Args:
        magic_number: Integer (0 = clinched), or None.
        standings: Our standings dict for division rank context.
        clinched_override: If True, render the clinched message regardless of
            the magic_number value. Used when playoff_race["clinched"] is True
            but magic_number hasn't been calculated to 0 yet (e.g. division
            clinch path not captured by the conference formula).

    Returns:
        HTML string for the magic number line, or empty string.
    """
    if magic_number is None:
        return ""

    if magic_number == 0 or clinched_override:
        label = "Playoff Spot Clinched"
        number_html = "✓"
    else:
        label = "Magic Number to Clinch"
        number_html = str(magic_number)

    return f"""
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#000616;">
      <tr>
        <td style="padding:14px 16px;font-family:{FONT_DATA};font-size:11px;font-weight:700;letter-spacing:2px;color:#8a93a8;text-transform:uppercase;">{label}</td>
        <td style="padding:14px 16px;font-family:{FONT_EDITORIAL};font-size:24px;font-weight:800;color:#d53e00;text-align:right;letter-spacing:-0.5px;line-height:1;">{number_html}</td>
      </tr>
    </table>
    """
