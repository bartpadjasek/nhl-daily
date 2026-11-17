"""Content cards: header and preheader, briefing, What We Learned, On This Day
and fine print.
"""

from emailer.theme import (
    ABBR,
    C_FINE_PRINT,
    C_LOSS,
    C_MID_BLUE,
    C_OTL,
    C_ROW_BORDER,
    C_WIN,
    FONT_DATA,
    FONT_EDITORIAL,
    NAME,
    NEWSLETTER,
    NICK,
    _section_marker,
    esc,
)

PREHEADER_MAX = 110


def _surname(name: str) -> str:
    parts = name.split(" ", 1)
    return parts[1] if len(parts) == 2 else name


def _get_preheader(data: dict) -> str:
    """Build the inbox preheader from game data (no API call).

    Complements the subject rather than repeating the score: up to two of our
    skaters with their line, the goalie's saves, then the next game with its
    full start string (display time zone), e.g.
    "Hyman 2G · Bouchard 1G 1A · Jarry 31 saves · Tonight @ TOR · Sun 15 Nov, 01:00 CET".

    At most PREHEADER_MAX characters; when too long, whole items are dropped
    (never cut mid-word). Returned HTML-escaped.
    """
    last_game = data.get("last_game") or {}
    skaters = []
    for sk in last_game.get("top_skaters", []):
        line = " ".join(
            part
            for part in (
                f"{sk.get('goals', 0)}G" if sk.get("goals") else "",
                f"{sk.get('assists', 0)}A" if sk.get("assists") else "",
            )
            if part
        )
        if line:
            skaters.append(f"{_surname(sk.get('name', ''))} {line}")
        if len(skaters) == 2:
            break

    goalie = last_game.get("goalie")
    goalie_item = f"{_surname(goalie['name'])} {goalie.get('saves', 0)} saves" if goalie else ""

    next_item = ""
    ng = data.get("next_game")
    if ng and ng.get("opponent"):
        sign = "vs" if ng.get("home_or_away") == "home" else "@"
        label = "Tonight" if ng.get("is_today") else "Next"
        next_item = f"{label} {sign} {ng['opponent']}"
        if ng.get("time"):
            next_item += f" \u00b7 {ng['time']}"

    # Drop order when over the limit: 2nd skater, goalie, 1st skater; next game stays.
    items = {"sk1": skaters[0] if skaters else "", "sk2": skaters[1] if len(skaters) > 1 else ""}
    items.update({"goalie": goalie_item, "next": next_item})
    order = ["sk1", "sk2", "goalie", "next"]

    def _join() -> str:
        return " \u00b7 ".join(items[k] for k in order if items[k])

    for drop in ("sk2", "goalie", "sk1"):
        if len(_join()) <= PREHEADER_MAX:
            break
        items[drop] = ""
    text = _join()
    if len(text) > PREHEADER_MAX:
        text = ""  # a lone next-game item over the limit — better empty than cut
    return esc(text)


def _build_header_html(subject_date: str, team_logo: str, data: dict | None = None) -> str:
    """Build the white email header with logo, date, and info strip.

    Args:
        subject_date: Human-readable date string, e.g. "Wednesday, March 26".
        team_logo: URL to our team logo image (SVG from NHL CDN).
        data: Full data dict; used to populate record, streak, next game strip.

    Returns:
        HTML string for the header block.
    """
    if data is None:
        data = {}

    # Info strip — only for regular season
    info_strip_html = ""
    if not data.get("playoff_bracket"):
        s = data.get("standings") or {}
        record_val = (
            f"{s['wins']}–{s['losses']}–{s['ot_losses']}" if s.get("wins") is not None else "—"
        )
        streak_raw = s.get("streak", "") or ""
        streak_color = (
            C_WIN if streak_raw.startswith("W") else C_LOSS if streak_raw.startswith("L") else C_OTL
        )
        streak_val = streak_raw or "—"

        ng = data.get("next_game") or {}
        if ng.get("opponent"):
            sign = "vs" if ng.get("home_or_away") == "home" else "@"
            next_val = f"{sign} {ng['opponent']}"
        else:
            next_val = "—"
        next_time_html = (
            f'<div style="font-family:{FONT_DATA};font-size:11px;font-weight:600;color:{C_MID_BLUE};margin-top:3px;">{ng["time"]}</div>'
            if ng.get("time")
            else ""
        )

        info_strip_html = f"""
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
    <tr><td style="padding:14px 28px 20px 28px;">
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="border-top:1px solid #eceef2;">
        <tr>
          <td style="padding:14px 0 0 0;" width="33%" valign="top">
            <div style="font-family:{FONT_DATA};font-size:10px;font-weight:700;letter-spacing:1.8px;color:#718096;text-transform:uppercase;">Record</div>
            <div style="font-family:{FONT_EDITORIAL};font-size:18px;font-weight:700;color:#000616;margin-top:4px;letter-spacing:-0.3px;">{record_val}</div>
          </td>
          <td style="padding:14px 0 0 0;" width="33%" valign="top">
            <div style="font-family:{FONT_DATA};font-size:10px;font-weight:700;letter-spacing:1.8px;color:#718096;text-transform:uppercase;">Streak</div>
            <div style="font-family:{FONT_EDITORIAL};font-size:18px;font-weight:700;color:{streak_color};margin-top:4px;letter-spacing:-0.3px;">{streak_val}</div>
          </td>
          <td style="padding:14px 0 0 0;" width="34%" valign="top">
            <div style="font-family:{FONT_DATA};font-size:10px;font-weight:700;letter-spacing:1.8px;color:#718096;text-transform:uppercase;">Next</div>
            <div style="font-family:{FONT_EDITORIAL};font-size:18px;font-weight:700;color:#000616;margin-top:4px;letter-spacing:-0.3px;">{next_val}</div>
            {next_time_html}
          </td>
        </tr>
      </table>
    </td></tr>
  </table>"""

    return f"""
    <tr>
      <td style="background:#ffffff;border-radius:14px 14px 0 0;padding:0;">

        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
          <tr><td style="height:6px;background:#d53e00;line-height:6px;font-size:0;border-radius:14px 14px 0 0;">&nbsp;</td></tr>
        </table>

        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
          <tr>
            <td style="padding:22px 28px 6px 28px;" align="left" valign="middle">
              <div style="font-family:{FONT_DATA};font-size:11px;font-weight:700;letter-spacing:2.5px;color:#d53e00;text-transform:uppercase;">{NEWSLETTER}</div>
              <div style="font-family:{FONT_EDITORIAL};font-size:30px;font-weight:800;color:#000616;letter-spacing:-0.5px;line-height:1.1;margin-top:6px;">{esc(subject_date)}</div>
            </td>
            <td style="padding:22px 28px 6px 0;" align="right" valign="top" width="72">
              <img src="https://assets.nhle.com/logos/nhl/svg/{ABBR}_light.svg" width="60" alt="{NAME}" style="display:block;width:60px;height:auto;border:0;outline:none;text-decoration:none;">
            </td>
          </tr>
        </table>

        {info_strip_html}

      </td>
    </tr>
    """


def _build_briefing_html(briefing: str) -> str:
    """Wrap the AI briefing text in a styled card section.

    Args:
        briefing: Plain-text briefing string (may contain paragraph breaks).

    Returns:
        HTML string for the briefing card.
    """
    paras = list(briefing.split("\n\n"))
    paragraphs = ""
    for idx, para in enumerate(paras):
        para = para.strip()
        if para:
            margin = "0" if idx == len(paras) - 1 else "0 0 14px 0"
            paragraphs += (
                f'<p style="font-family:{FONT_DATA};margin:{margin};font-size:16px;font-weight:400;line-height:1.7;color:#191c1e;">'
                f"{esc(para)}</p>"
            )

    return f"""
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
           style="background:#ffffff;border-radius:12px;overflow:hidden;">
      <tr><td style="padding:28px 28px 8px 28px;">
        {_section_marker("Today's Briefing")}
      </td></tr>
      <tr><td style="padding:18px 28px 26px 28px;">
        {paragraphs}
      </td></tr>
    </table>
    """


def _build_what_we_learned_html(takeaways: list) -> str:
    """Build the 'What We Learned' card — up to 3 punchy post-game takeaways.

    Args:
        takeaways: List of 3 one-sentence strings from digest.generate_what_we_learned().

    Returns:
        HTML string for the card, or empty string if no data.
    """
    if not takeaways:
        return ""

    items = ""
    for i, point in enumerate(takeaways[:3], start=1):
        point_escaped = esc(point)
        if i > 1:
            items += f'<tr><td colspan="2" style="border-top:1px solid {C_ROW_BORDER};line-height:0;font-size:0;">&nbsp;</td></tr>'
        pad_top = "6px" if i == 1 else "14px"
        items += (
            f"<tr>"
            f'<td width="36" valign="top" style="font-family:{FONT_EDITORIAL};font-size:18px;font-weight:800;color:#d53e00;padding:{pad_top} 0 6px 0;line-height:1;">{i}</td>'
            f'<td valign="top" style="padding:{pad_top} 0 6px 0;font-family:{FONT_DATA};font-size:15px;line-height:1.55;color:#191c1e;">'
            f"{point_escaped}</td>"
            f"</tr>"
        )

    return f"""
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
           style="background:#ffffff;border-radius:12px;overflow:hidden;">
      <tr><td style="padding:28px 28px 8px 28px;">
        {_section_marker("What We Learned")}
      </td></tr>
      <tr><td style="padding:18px 28px 24px 28px;">
        <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%">
          {items}
        </table>
      </td></tr>
    </table>
    """


def _build_on_this_day_section(on_this_day: dict | None) -> str:
    """Build the 'On This Day in team history' callout box.

    Args:
        on_this_day: Dict with 'text' and 'source', or None.

    Returns:
        HTML string for the callout, or empty string if no data.
    """
    if not on_this_day or not on_this_day.get("text"):
        return ""

    text = esc(on_this_day["text"])
    body_text = text
    title_html = ""
    year_html = f'<div style="font-family:{FONT_EDITORIAL};font-size:11px;font-weight:700;color:#d53e00;letter-spacing:2px;text-transform:uppercase;margin-top:14px;">{NICK} History</div>'

    # On This Day section marker with white text
    marker_html = (
        f'<table role="presentation" cellpadding="0" cellspacing="0" border="0">'
        f'<tr><td style="border-left:3px solid #d53e00;padding-left:12px;'
        f"font-family:{FONT_DATA};font-size:11px;font-weight:700;letter-spacing:2.5px;"
        f'color:#ffffff;text-transform:uppercase;line-height:1.2;">On This Day</td></tr>'
        f"</table>"
    )

    return f"""
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
           style="background:#041e42;border-radius:12px;overflow:hidden;">
      <tr><td style="padding:24px 28px 8px 28px;">
        {marker_html}
        {year_html}
        {title_html}
      </td></tr>
      <tr><td style="padding:14px 28px 28px 28px;">
        <p style="font-family:{FONT_DATA};font-size:14px;line-height:1.6;color:#a8b3cc;margin:0;">{body_text}</p>
      </td></tr>
    </table>"""


def _build_fine_print_html(text: str) -> str:
    """Build the fine print disclaimer at the bottom of the email.

    Args:
        text: One-sentence disclaimer from digest.generate_fine_print().

    Returns:
        HTML string for the fine print footer.
    """
    if not text:
        return ""

    escaped = esc(text)
    return (
        f'<p style="margin:0;font-size:12px;color:{C_FINE_PRINT};font-style:italic;'
        f'line-height:1.5;">{escaped}.</p>'
    )
