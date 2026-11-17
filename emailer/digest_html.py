"""Assembles the digest HTML page, shrinks it (_finalize_html) and renders the
finished email (render_email) for sending or preview.
"""

import logging
import re

import run_report
from config import SETTINGS
from emailer.cards_content import (
    _build_briefing_html,
    _build_fine_print_html,
    _build_header_html,
    _build_on_this_day_section,
    _build_what_we_learned_html,
    _get_preheader,
)
from emailer.cards_form import (
    _build_season_5v5_html,
    _build_series_and_form_html,
    _build_suffer_o_meter_html,
)
from emailer.cards_game import (
    _build_last_game_html,
    _build_scoring_summary_html,
    _build_three_stars_html,
)
from emailer.cards_next import _build_next_game_html, _build_upcoming_schedule_html
from emailer.cards_people import (
    _build_injury_section_html,
    _build_player_of_week_html,
    _build_prospects_section,
    _build_top_scorers_html,
)
from emailer.cards_playoffs import _build_playoff_bracket_html
from emailer.cards_standings import (
    _build_conference_standings_html,
    _build_magic_number_html,
    _build_playoff_race_section,
)
from emailer.plaintext import build_plain_text
from emailer.theme import C_FOOTER_TEXT, FONT_DATA, FONT_EDITORIAL, NEWSLETTER, esc

logger = logging.getLogger(__name__)


def build_html(briefing: str, data: dict, subject_date: str) -> str:
    """Assemble the complete mobile-first HTML email body.

    Sections (in order; a card with no data renders nothing):
    1. Header — team logo, subject, record / streak / next game strip
    2. Last Game — score (OT/SO, SHUTOUT), date/venue, team stats, both goalies, recap link
    3. Today's Briefing (AI)
    4. Next Up — matchup, start time (display time zone), back-to-back / trip line, opponent
       preview, weather
    5. Suffer-O-Meter — 1-10 score with reasons
    6. Goal Log
    7. Three Stars
    8. Series · Form — season series vs the last opponent, last 10 results
       (Playoff Series view in the playoffs)
    9. Season 5v5 — CF%, FF%, PDO and a one-line reading
    10. What We Learned (AI)
    11. On This Day (Wikipedia only)
    12. Injury Report
    13. Western Conference standings with the magic number, OR the playoff bracket
    14. Playoff Race (regular season, from MAGIC_NUMBER_MIN_GP games, pre-clinch)
    15. Team Leaders (top scorers)
    16. Player of the Week · Milestones
    17. Prospects
    18. Coming Up — the games after Next Up
    19. Footer — missing-data line and fine print

    Styles are inline except the font classes and the mobile media query in the
    <style> block (see _finalize_html). Max content width 600px.

    Args:
        briefing: Plain-text AI-generated briefing.
        data: Structured data dict from nhl.get_team_data().
        subject_date: Formatted date string, e.g. "Wednesday, March 26".

    Returns:
        Complete HTML string ready to use as email body.
    """
    preheader = _get_preheader(data)
    team_logo = data.get("team_logo", "")
    last_game = data.get("last_game")

    header_html = _build_header_html(subject_date, team_logo, data)
    last_game_html = _build_last_game_html(last_game, data.get("advanced_stats"))
    suffer_html = _build_suffer_o_meter_html(data.get("suffer_score"))
    scoring_html = _build_scoring_summary_html(last_game)
    three_stars_html = _build_three_stars_html(last_game)
    series_form_html = _build_series_and_form_html(last_game, data.get("recent_form"), data)
    season_5v5_html = _build_season_5v5_html(data.get("advanced_stats"))
    briefing_html = _build_briefing_html(briefing)
    what_we_learned_html = _build_what_we_learned_html(data.get("what_we_learned", []))
    fine_print_html = _build_fine_print_html(data.get("fine_print", ""))
    top_scorers_html = _build_top_scorers_html(
        data.get("top_scorers", []), is_playoffs=bool(data.get("playoff_scorers"))
    )
    pow_milestones_html = _build_player_of_week_html(
        data.get("player_of_week"), data.get("milestones", [])
    )
    prospects_html = _build_prospects_section(data.get("prospects", []))
    on_this_day_html = _build_on_this_day_section(data.get("on_this_day"))
    next_game_html = _build_next_game_html(
        data.get("next_game"),
        data.get("next_game_preview"),
        data.get("road_weather"),
        data.get("schedule_notes"),
    )
    injury_html = _build_injury_section_html(data.get("injuries", []))
    # Next Up shows the first upcoming game; Coming Up shows the rest
    upcoming_html = _build_upcoming_schedule_html(data.get("upcoming_games", []))

    playoff_bracket = data.get("playoff_bracket")
    conference_standings = data.get("conference_standings")
    playoff_race_html = "" if playoff_bracket else _build_playoff_race_section(data)
    magic_number_html = _build_magic_number_html(
        data.get("magic_number"),
        data.get("standings") or {},
        clinched_override=(data.get("playoff_race") or {}).get("clinched", False),
    )

    if playoff_bracket:
        standings_section_html = _build_playoff_bracket_html(playoff_bracket)
    else:
        standings_raw = _build_conference_standings_html(conference_standings)
        # Inject magic number callout inside the standings section (before table body)
        if magic_number_html and standings_raw:
            # Insert magic number between the section marker row and the standings table row
            magic_inject = (
                f'<tr><td style="padding:14px 28px 8px 28px;">{magic_number_html}</td></tr>'
            )
            standings_section_html = standings_raw.replace(
                '<tr><td style="padding:14px 28px 14px 28px;">',
                magic_inject + '<tr><td style="padding:14px 28px 14px 28px;">',
                1,
            )
        else:
            standings_section_html = standings_raw

    # Cards turned off in config.toml [email] hide_cards
    hidden = SETTINGS.hide_cards
    if hidden:
        next_game_html = "" if "next_up" in hidden else next_game_html
        suffer_html = "" if "suffer_o_meter" in hidden else suffer_html
        scoring_html = "" if "goal_log" in hidden else scoring_html
        three_stars_html = "" if "three_stars" in hidden else three_stars_html
        series_form_html = "" if "series_form" in hidden else series_form_html
        season_5v5_html = "" if "season_5v5" in hidden else season_5v5_html
        what_we_learned_html = "" if "what_we_learned" in hidden else what_we_learned_html
        on_this_day_html = "" if "on_this_day" in hidden else on_this_day_html
        injury_html = "" if "injuries" in hidden else injury_html
        standings_section_html = "" if "standings" in hidden else standings_section_html
        playoff_race_html = "" if "playoff_race" in hidden else playoff_race_html
        top_scorers_html = "" if "team_leaders" in hidden else top_scorers_html
        pow_milestones_html = "" if "player_of_the_week" in hidden else pow_milestones_html
        prospects_html = "" if "prospects" in hidden else prospects_html
        upcoming_html = "" if "coming_up" in hidden else upcoming_html

    missing_line = run_report.footer_line(data.get("missing_data") or [])
    missing_html = (
        f'<div style="font-family:{FONT_DATA};font-size:12px;color:{C_FOOTER_TEXT};margin-top:8px;line-height:1.5;">'
        f"{esc(missing_line)}</div>"
        if missing_line
        else ""
    )

    def _section_row(html: str, first: bool = False) -> str:
        """Wrap a section html in a <tr><td> with correct background and spacing."""
        if not html.strip():
            return ""
        pad = "padding:0;" if first else "padding:20px 0 0 0;"
        return f'<tr><td style="background:#eceef2;{pad}">{html}</td></tr>'

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta http-equiv="X-UA-Compatible" content="IE=edge">
  <title>{NEWSLETTER}</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Work+Sans:wght@700;800&family=Inter:wght@400;600;700&display=swap" rel="stylesheet">
  <style>
    .fd {{ font-family:{FONT_DATA}; }}
    .fe {{ font-family:{FONT_EDITORIAL}; }}
    @media only screen and (max-width:480px) {{
      .od-outer {{ padding:12px 6px !important; }}
      .od-big {{ font-size:24px !important; }}
    }}
  </style>
</head>
<body style="margin:0;padding:0;background:#eceef2;font-family:{FONT_DATA};color:#191c1e;-webkit-font-smoothing:antialiased;">

  <div style="display:none;max-height:0;overflow:hidden;font-size:1px;line-height:1px;color:#eceef2;">
    {preheader}
    &nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;
    &nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;
  </div>

  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#eceef2;">
    <tr><td class="od-outer" align="center" style="padding:24px 16px;font-family:{FONT_DATA};">

      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="width:100%;max-width:600px;">

        {header_html}

        {_section_row(last_game_html, first=True)}
        {_section_row(briefing_html)}
        {_section_row(next_game_html)}
        {_section_row(suffer_html)}
        {_section_row(scoring_html)}
        {_section_row(three_stars_html)}
        {_section_row(series_form_html)}
        {_section_row(season_5v5_html)}
        {_section_row(what_we_learned_html)}
        {_section_row(on_this_day_html)}
        {_section_row(injury_html)}
        {_section_row(standings_section_html)}
        {_section_row(playoff_race_html)}
        {_section_row(top_scorers_html)}
        {_section_row(pow_milestones_html)}
        {_section_row(prospects_html)}
        {_section_row(upcoming_html)}

        <tr>
          <td style="background:#000616;border-radius:0 0 14px 14px;padding:32px 28px 24px 28px;">
            <div style="font-family:{FONT_EDITORIAL};font-size:14px;font-weight:800;color:#ffffff;letter-spacing:0.5px;">{NEWSLETTER}</div>
            <div style="font-family:{FONT_DATA};font-size:12px;color:#6b7590;margin-top:6px;">Powered by NHL API &amp; AI &middot; sent the morning after every game</div>
            {missing_html}
            <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="margin-top:18px;">
              <tr><td style="border-top:1px solid #1a2540;padding-top:14px;font-family:{FONT_DATA};">{fine_print_html}</td></tr>
            </table>
          </td>
        </tr>

      </table>

    </td></tr>
  </table>

</body>
</html>"""


# Gmail clips messages at roughly 102 KB; warn well before that.
HTML_SIZE_WARN_BYTES = 95_000


_START_TAG_RE = re.compile(r"<([a-zA-Z][a-zA-Z0-9]*)(\s[^<>]*?)?(/?)>")


_STYLE_ATTR_RE = re.compile(r'style="([^"]*)"')


_CLASS_ATTR_RE = re.compile(r'class="([^"]*)"')


_BETWEEN_TAGS_WS_RE = re.compile(r">\s+<")


def _finalize_html(html: str) -> str:
    """Shrink the digest HTML before sending (keeps it under Gmail's clip limit).

    1. Replace inline `font-family:FONT_DATA` / `FONT_EDITORIAL` declarations with
       the `fd` / `fe` classes defined in the <style> block. <body> and the outer
       wrapper cell (class "od-outer") keep their inline FONT_DATA so clients that
       strip <style> still get the body font.
    2. Collapse each run of whitespace between tags to one space, or one newline
       if the run contained a newline — never to nothing, since inline elements
       rely on that space.
    """
    fonts = {FONT_DATA: "fd", FONT_EDITORIAL: "fe"}

    def _tag(m: re.Match) -> str:
        name, attrs, slash = m.group(1), m.group(2) or "", m.group(3)
        if name.lower() == "body" or "od-outer" in attrs or "font-family:" not in attrs:
            return m.group(0)
        style_m = _STYLE_ATTR_RE.search(attrs)
        if not style_m:
            return m.group(0)
        style = style_m.group(1)
        added = None
        for font, cls in fonts.items():
            decl = f"font-family:{font}"
            if decl in style:
                style = style.replace(decl + ";", "").replace(decl, "")
                added = cls
                break
        if not added:
            return m.group(0)
        style = style.strip().strip(";").strip()
        attrs = (
            attrs[: style_m.start()]
            + (f'style="{style}"' if style else "")
            + attrs[style_m.end() :]
        )
        class_m = _CLASS_ATTR_RE.search(attrs)
        if class_m:
            attrs = (
                attrs[: class_m.start()]
                + f'class="{class_m.group(1)} {added}"'
                + attrs[class_m.end() :]
            )
        else:
            attrs = f' class="{added}"' + attrs
        if not style:  # style attribute removed — tidy the leftover double space
            attrs = re.sub(r"\s{2,}", " ", attrs).rstrip()
        return f"<{name}{attrs}{slash}>"

    html = _START_TAG_RE.sub(_tag, html)
    return _BETWEEN_TAGS_WS_RE.sub(lambda m: ">\n<" if "\n" in m.group(0) else "> <", html)


def render_email(subject: str, briefing: str, data: dict) -> tuple[str, str]:
    """Build the finished HTML and plain-text bodies exactly as they are sent.

    Shared by send_email and preview mode so the preview is the real email.
    Logs the HTML size and warns when it nears Gmail's clip limit.
    """
    subject_date = subject.replace(f"{NEWSLETTER} \u2014 ", "").strip()
    html_body = _finalize_html(build_html(briefing, data, subject_date))
    plain_body = build_plain_text(briefing, data, subject_date)

    html_bytes = len(html_body.encode("utf-8"))
    logger.info("Digest HTML size: %d bytes", html_bytes)
    if html_bytes > HTML_SIZE_WARN_BYTES:
        logger.warning(
            "Digest HTML is %d bytes (> %d) — Gmail clips at ~102 KB",
            html_bytes,
            HTML_SIZE_WARN_BYTES,
        )
    return html_body, plain_body
