"""Season recap email HTML."""

import re

from emailer.theme import (
    ABBR,
    C_LOSS,
    C_ON_PRIMARY,
    C_ON_SURFACE,
    C_ON_SURFACE_MED,
    C_ON_SURFACE_MUTED,
    C_PRIMARY,
    C_ROW_BORDER,
    C_SECONDARY_CONT,
    C_SURFACE,
    C_SURFACE_LOW,
    C_SURFACE_LOWEST,
    C_WIN,
    FONT_DATA,
    FONT_EDITORIAL,
    NAME,
    NEWSLETTER,
    NICK,
    _section_marker,
    _team_logo_url,
    esc,
)


def _clean_recap_text(text: str) -> list[str]:
    """Clean AI-generated recap text and return a list of paragraph strings.

    Web search citations and mid-sentence line breaks from the agentic loop
    can split sentences across paragraphs. This function:
    - Strips citation markers like [1], [2], 【1†source】
    - Strips markdown horizontal rules (---, ***)
    - Re-joins fragments that start with punctuation or a lowercase letter
      onto the previous paragraph (they are mid-sentence continuations)
    """
    # Remove citation markers from web search
    text = re.sub(r"\【\d+†[^\】]*\】", "", text)
    text = re.sub(r"\[\d+\]", "", text)
    # Remove markdown horizontal rules
    text = re.sub(r"^\s*[-*_]{3,}\s*$", "", text, flags=re.MULTILINE)

    _PREAMBLE = re.compile(
        r"^(the research is|here'?s? (the|my|a)|based on (my|the)|let me|i (have|will|'ve)|"
        r"after (reviewing|researching|searching)|following (my|the))",
        re.IGNORECASE,
    )

    raw = [p.strip() for p in text.split("\n\n") if p.strip()]

    # Drop any leading paragraph that is meta-commentary rather than content
    while raw and _PREAMBLE.match(raw[0]):
        raw.pop(0)

    merged: list[str] = []
    for fragment in raw:
        # Merge fragments that are clearly mid-sentence continuations:
        # starts with punctuation, lowercase, em dash, or a bare period
        is_continuation = merged and (
            fragment[0] in ",;:—"  # comma, semicolon, colon, em dash
            or fragment[0].islower()
            or fragment.startswith(". ")  # period left over from a cut sentence
        )
        if is_continuation:
            prev = merged[-1].rstrip()
            # Don't double-up a period if the previous fragment already ends with one
            sep = "" if prev.endswith(".") and fragment.startswith(". ") else " "
            merged[-1] = prev + sep + fragment.lstrip(". ").lstrip()
        else:
            merged.append(fragment)
    return merged


def build_recap_html(recap_data: dict) -> str:
    """Build the season recap email HTML.

    Args:
        recap_data: Dict produced by season_recap.py with keys:
            overview, good_bad_middling, player_grades, offseason_priorities,
            last_game, standings, playoff_bracket, top_scorers.

    Returns:
        Complete HTML string for the recap email.
    """
    team_logo = _team_logo_url(f"{ABBR}", "light")

    last_game = recap_data.get("last_game") or {}
    standings = recap_data.get("standings") or {}

    season_label = ""
    lg_date = last_game.get("date", "")
    if lg_date:
        try:
            yr = int(lg_date[:4])
            mo = int(lg_date[5:7])
            if mo < 7:
                season_label = f"{yr - 1}–{str(yr)[2:]}"
            else:
                season_label = f"{yr}–{str(yr + 1)[2:]}"
        except (ValueError, IndexError):
            pass

    record_val = ""
    if standings.get("wins") is not None:
        record_val = f"{standings['wins']}–{standings['losses']}–{standings.get('ot_losses', 0)}"

    def _section_row(html: str, first: bool = False) -> str:
        if not html.strip():
            return ""
        pad = "padding:0;" if first else "padding:20px 0 0 0;"
        return f'<tr><td style="background:{C_SURFACE};{pad}">{html}</td></tr>'

    # Header
    record_badge = (
        f'<span style="display:inline-block;margin-top:10px;background:rgba(255,255,255,0.12);'
        f"border-radius:4px;padding:4px 12px;font-family:{FONT_DATA};font-size:13px;"
        f'font-weight:700;color:{C_ON_PRIMARY};">{record_val}</span>'
        if record_val
        else ""
    )
    header_html = f"""
    <tr>
      <td style="background:{C_PRIMARY};border-radius:14px 14px 0 0;padding:0;">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
          <tr><td style="height:6px;background:{C_SECONDARY_CONT};line-height:6px;font-size:0;border-radius:14px 14px 0 0;">&nbsp;</td></tr>
        </table>
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
          <tr>
            <td style="padding:22px 28px 28px 28px;" valign="middle">
              <div style="font-family:{FONT_DATA};font-size:11px;font-weight:700;letter-spacing:2.5px;color:{C_SECONDARY_CONT};text-transform:uppercase;">Season Review</div>
              <div style="font-family:{FONT_EDITORIAL};font-size:30px;font-weight:800;color:{C_ON_PRIMARY};letter-spacing:-0.5px;line-height:1.1;margin-top:6px;">{season_label or "{NICK}"} Season</div>
              {record_badge}
            </td>
            <td style="padding:22px 28px 28px 0;" align="right" valign="top" width="72">
              <img src="{team_logo}" width="60" alt="{NAME}" style="display:block;width:60px;height:auto;border:0;outline:none;text-decoration:none;">
            </td>
          </tr>
        </table>
      </td>
    </tr>"""

    # Season Overview
    overview_text = recap_data.get("overview", "")
    overview_html = ""
    if overview_text:
        paras = _clean_recap_text(overview_text)
        paras_html = "".join(
            f'<p style="margin:0 0 14px 0;font-family:{FONT_DATA};font-size:16px;'
            f'line-height:1.65;color:{C_ON_SURFACE};">{esc(p)}</p>'
            for p in paras
        )
        overview_html = (
            f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"'
            f' style="background:{C_SURFACE_LOWEST};border-radius:12px;overflow:hidden;">'
            f'<tr><td style="padding:24px 28px 12px 28px;">{_section_marker("Season Overview")}</td></tr>'
            f'<tr><td style="padding:12px 28px 24px 28px;">{paras_html}</td></tr>'
            f"</table>"
        )

    # Good / Bad / Middling
    gbd = recap_data.get("good_bad_middling") or {}

    _BOLD_TITLE = re.compile(r"^\*\*(.+?)\*\*\s*(.*)", re.DOTALL)

    def _render_gbd_paras(text: str, accent_color: str) -> str:
        """Render GBD prose, converting **Title** lines into styled sub-headers."""
        blocks = ""
        for para in _clean_recap_text(text):
            m = _BOLD_TITLE.match(para)
            if m:
                title, body = m.group(1).strip(), m.group(2).strip()
                blocks += (
                    f'<div style="font-family:{FONT_DATA};font-size:14px;font-weight:700;'
                    f'color:{accent_color};margin:16px 0 4px 0;">{esc(title)}</div>'
                )
                if body:
                    blocks += (
                        f'<p style="margin:0 0 4px 0;font-family:{FONT_DATA};font-size:15px;'
                        f'line-height:1.6;color:{C_ON_SURFACE};">{esc(body)}</p>'
                    )
            else:
                blocks += (
                    f'<p style="margin:0 0 4px 0;font-family:{FONT_DATA};font-size:15px;'
                    f'line-height:1.6;color:{C_ON_SURFACE};">{esc(para)}</p>'
                )
        return blocks

    def _gbd_card(label: str, color: str, text: str) -> str:
        if not text:
            return ""
        body_html = _render_gbd_paras(text, color)
        return (
            f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"'
            f' style="background:{C_SURFACE_LOWEST};border-radius:12px;overflow:hidden;margin-bottom:12px;">'
            f"<tr>"
            f'<td style="width:4px;background:{color};padding:0;font-size:0;line-height:0;">&nbsp;</td>'
            f'<td style="padding:20px 24px 20px 20px;">'
            f'<div style="font-family:{FONT_DATA};font-size:11px;font-weight:700;letter-spacing:2px;'
            f'text-transform:uppercase;color:{color};margin-bottom:4px;">{label}</div>'
            f"{body_html}"
            f"</td>"
            f"</tr>"
            f"</table>"
        )

    good_card = _gbd_card("The Good", C_WIN, gbd.get("good", ""))
    bad_card = _gbd_card("The Bad", C_LOSS, gbd.get("bad", ""))
    middling_card = _gbd_card("The Middling", "#c8860a", gbd.get("middling", ""))

    gbd_html = ""
    if any([good_card, bad_card, middling_card]):
        gbd_html = (
            f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">'
            f'<tr><td style="padding:0 0 16px 0;">{_section_marker("The Verdict")}</td></tr>'
            f"<tr><td>{good_card}{bad_card}{middling_card}</td></tr>"
            f"</table>"
        )

    # Player Grades
    player_grades = recap_data.get("player_grades") or []
    grades_html = ""
    if player_grades:

        def _grade_chip(grade: str) -> str:
            first = grade[0].upper() if grade else "?"
            color = {"A": C_WIN, "B": "#4a7fc1", "C": "#c8860a"}.get(first, C_LOSS)
            return (
                f'<span style="display:inline-block;background:{color};color:#fff;'
                f"font-family:{FONT_DATA};font-size:13px;font-weight:700;"
                f'padding:3px 9px;border-radius:4px;min-width:28px;text-align:center;">'
                f"{esc(grade)}</span>"
            )

        rows_html = ""
        for i, pg in enumerate(player_grades):
            bg = C_SURFACE_LOWEST if i % 2 == 0 else C_SURFACE_LOW
            rows_html += (
                f'<tr style="background:{bg};">'
                f'<td style="padding:10px 16px;font-family:{FONT_DATA};font-size:14px;'
                f'font-weight:600;color:{C_ON_SURFACE};">{esc(pg.get("name", ""))}</td>'
                f'<td style="padding:10px 8px;font-family:{FONT_DATA};font-size:13px;'
                f'color:{C_ON_SURFACE_MUTED};">{esc(pg.get("position", ""))}</td>'
                f'<td style="padding:10px 8px;text-align:center;">{_grade_chip(pg.get("grade", "?"))}</td>'
                f'<td style="padding:10px 16px 10px 8px;font-family:{FONT_DATA};font-size:13px;'
                f'color:{C_ON_SURFACE_MED};line-height:1.4;">{esc(pg.get("reasoning", ""))}</td>'
                f"</tr>"
            )

        grades_html = (
            f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"'
            f' style="background:{C_SURFACE_LOWEST};border-radius:12px;overflow:hidden;">'
            f'<tr><td colspan="4" style="padding:20px 28px 12px 28px;">'
            f"{_section_marker('Player Grades')}</td></tr>"
            f'<tr><td colspan="4" style="padding:0;">'
            f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">'
            f"{rows_html}"
            f"</table></td></tr>"
            f"</table>"
        )

    # Offseason Priorities
    priorities = recap_data.get("offseason_priorities") or []
    priorities_html = ""
    if priorities:

        def _priority_pill(label: str) -> str:
            bg = {"Critical": C_LOSS, "Important": C_SECONDARY_CONT}.get(label, C_ON_SURFACE_MUTED)
            return (
                f'<span style="display:inline-block;background:{bg};color:#fff;'
                f"font-family:{FONT_DATA};font-size:10px;font-weight:700;letter-spacing:1px;"
                f"text-transform:uppercase;padding:2px 8px;border-radius:3px;"
                f'vertical-align:middle;margin-left:8px;">{esc(label)}</span>'
            )

        items_html = ""
        for i, p in enumerate(priorities, 1):
            border = f"border-bottom:1px solid {C_ROW_BORDER};" if i < len(priorities) else ""
            items_html += (
                f"<tr>"
                f'<td style="padding:14px 12px 14px 24px;vertical-align:top;'
                f"font-family:{FONT_DATA};font-size:16px;font-weight:700;"
                f'color:{C_SECONDARY_CONT};width:28px;">{i}.</td>'
                f'<td style="padding:14px 24px 14px 0;{border}">'
                f'<div style="font-family:{FONT_DATA};font-size:14px;font-weight:700;'
                f'color:{C_ON_SURFACE};margin-bottom:4px;">'
                f"{esc(p.get('priority', ''))}"
                f"{_priority_pill(p.get('label', 'Monitor'))}"
                f"</div>"
                f'<div style="font-family:{FONT_DATA};font-size:13px;color:{C_ON_SURFACE_MED};'
                f'line-height:1.5;">{esc(p.get("detail", ""))}</div>'
                f"</td>"
                f"</tr>"
            )

        priorities_html = (
            f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"'
            f' style="background:{C_SURFACE_LOWEST};border-radius:12px;overflow:hidden;">'
            f'<tr><td colspan="2" style="padding:20px 28px 12px 28px;">'
            f"{_section_marker('Offseason Priorities')}</td></tr>"
            f'<tr><td colspan="2" style="padding:0;">'
            f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">'
            f"{items_html}"
            f"</table></td></tr>"
            f"</table>"
        )

    footer_html = (
        f'<tr><td style="background:{C_PRIMARY};border-radius:0 0 14px 14px;padding:32px 28px 24px 28px;">'
        f'<div style="font-family:{FONT_EDITORIAL};font-size:14px;font-weight:800;'
        f'color:{C_ON_PRIMARY};letter-spacing:0.5px;">{NEWSLETTER}</div>'
        f'<div style="font-family:{FONT_DATA};font-size:12px;color:#6b7590;margin-top:6px;">'
        f"Powered by NHL API &amp; AI &middot; {season_label or 'Season'} Recap</div>"
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"'
        f' style="margin-top:18px;">'
        f'<tr><td style="border-top:1px solid #1a2540;padding-top:14px;font-family:{FONT_DATA};'
        f'font-size:12px;font-style:italic;color:#8a93a8;line-height:1.5;">'
        f"See you next season. Go {NICK}.</td></tr>"
        f"</table>"
        f"</td></tr>"
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta http-equiv="X-UA-Compatible" content="IE=edge">
  <title>{NEWSLETTER} — Season Recap</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Work+Sans:wght@700;800&family=Inter:wght@400;600;700&display=swap" rel="stylesheet">
  <style>
    @media only screen and (max-width:480px) {{
      .od-outer {{ padding:12px 6px !important; }}
      .od-big {{ font-size:24px !important; }}
    }}
  </style>
</head>
<body style="margin:0;padding:0;background:{C_SURFACE};font-family:{FONT_DATA};color:{C_ON_SURFACE};-webkit-font-smoothing:antialiased;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background:{C_SURFACE};">
    <tr><td class="od-outer" align="center" style="padding:24px 16px;">
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="width:100%;max-width:600px;">
        {header_html}
        {_section_row(overview_html, first=True)}
        {_section_row(gbd_html)}
        {_section_row(grades_html)}
        {_section_row(priorities_html)}
        {footer_html}
      </table>
    </td></tr>
  </table>
</body>
</html>"""
