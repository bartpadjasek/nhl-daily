"""Form cards: season series and recent form, Suffer-O-Meter, Season 5v5."""

from emailer.cards_playoffs import _build_playoff_series_view_html
from emailer.theme import (
    C_LOSS,
    C_MID_BLUE,
    C_ON_SURFACE_MED,
    C_SECONDARY,
    C_SURFACE_LOW,
    C_WIN,
    FONT_DATA,
    FONT_EDITORIAL,
    _section_marker,
    esc,
)


def five_v_five_reading(corsi: float | None, pdo: float | None) -> str:
    """One line of reading for the Season 5v5 card, built in code.

    CF% 52+ "controlling play", 48-52 "roughly even", under 48 "being outshot";
    PDO over 102 "percentages running hot", 98-102 "about normal", under 98
    "running cold".
    """
    parts = []
    if corsi is not None:
        if corsi >= 52:
            parts.append("Controlling play at 5v5")
        elif corsi >= 48:
            parts.append("Roughly even at 5v5")
        else:
            parts.append("Being outshot at 5v5")
    if pdo is not None:
        if pdo > 102:
            words = "percentages running hot"
        elif pdo >= 98:
            words = "percentages about normal"
        else:
            words = "percentages running cold"
        parts.append(f"with {words}" if parts else words.capitalize())
    return (", ".join(parts) + ".") if parts else ""


def _build_season_5v5_html(advanced_stats: dict | None) -> str:
    """Season 5v5 card: shot attempts (CF%), unblocked attempts (FF%), PDO, and a reading."""
    if not advanced_stats:
        return ""
    corsi = advanced_stats.get("corsi_pct")
    fenwick = advanced_stats.get("fenwick_pct")
    pdo = advanced_stats.get("pdo")

    def _cell(label: str, value: str, border_right: bool) -> str:
        br = "border-right:2px solid #ffffff;" if border_right else ""
        return (
            f'<td width="33%" valign="top" style="padding:14px 12px;background:{C_SURFACE_LOW};{br}">'
            f'<div style="font-family:{FONT_EDITORIAL};font-size:22px;font-weight:800;color:#041e42;letter-spacing:-0.5px;">{value}</div>'
            f'<div style="font-family:{FONT_DATA};font-size:11px;font-weight:600;color:{C_MID_BLUE};margin-top:4px;line-height:1.3;">{label}</div>'
            f"</td>"
        )

    pct = f'<span style="font-size:13px;color:{C_MID_BLUE};font-weight:600;">%</span>'
    items = []
    if corsi is not None:
        items.append(("Shot attempts (CF%)", f"{corsi}{pct}"))
    if fenwick is not None:
        items.append(("Unblocked attempts (FF%)", f"{fenwick}{pct}"))
    if pdo is not None:
        items.append(("PDO", str(pdo)))
    if not items:
        return ""
    cells = "".join(
        _cell(label, value, border_right=i < len(items) - 1)
        for i, (label, value) in enumerate(items)
    )
    reading = five_v_five_reading(corsi, pdo)
    reading_html = (
        f'<p style="margin:14px 0 0;font-family:{FONT_DATA};font-size:14px;line-height:1.5;color:{C_ON_SURFACE_MED};">{reading}</p>'
        if reading
        else ""
    )
    return f"""
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
           style="background:#ffffff;border-radius:12px;overflow:hidden;">
      <tr><td style="padding:28px 28px 8px 28px;">
        {_section_marker("Season 5v5")}
      </td></tr>
      <tr><td style="padding:14px 28px 24px 28px;">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
          <tr>{cells}</tr>
        </table>
        {reading_html}
      </td></tr>
    </table>
    """


def _build_series_and_form_html(
    last_game: dict, recent_form: dict, data: dict | None = None
) -> str:
    """Build the combined season series + recent form row, or playoff series view.

    During playoffs, shows the current best-of-7 series record instead of
    regular season head-to-head and Last 10 form.

    Args:
        last_game: The last_game dict from nhl.get_team_data().
        recent_form: The recent_form dict from nhl.get_team_data().
        data: Full data dict; used to detect playoff mode.

    Returns:
        HTML string for the combined row, or empty string if no data.
    """
    # Playoff mode: show current series record, not regular season stats
    playoff_bracket = (data or {}).get("playoff_bracket")
    if playoff_bracket:
        return _build_playoff_series_view_html(playoff_bracket)

    has_series = last_game and last_game.get("season_series")
    has_form = recent_form and (recent_form.get("games") or recent_form.get("record"))
    if not has_series and not has_form:
        return ""

    # Season series box
    if has_series:
        ss = last_game["season_series"]
        opp = last_game.get("opponent", "OPP")
        record_str = f"{ss['wins']}–{ss['losses']}–{ss['ot_losses']}"
        series_cell = (
            f'<td width="50%" valign="top" style="padding:14px;background:#f8f9fb;border-right:8px solid #ffffff;">'
            f'<div style="font-family:{FONT_DATA};font-size:10px;font-weight:700;letter-spacing:2px;color:#718096;text-transform:uppercase;">vs {opp} · Season</div>'
            f'<div style="font-family:{FONT_EDITORIAL};font-size:30px;font-weight:800;color:#191c1e;letter-spacing:-1px;margin-top:8px;line-height:1;white-space:nowrap;" class="od-big">{record_str}</div>'
            + "</td>"
        )
    else:
        series_cell = (
            '<td width="50%" style="background:#f8f9fb;border-right:8px solid #ffffff;"></td>'
        )

    # Recent form dots
    if has_form:
        dot_colors = {"W": C_WIN, "L": C_LOSS, "OTL": "#757575"}
        games = recent_form.get("games", [])
        record = recent_form.get("record", "")

        results: list[str] = [g.get("result", "") for g in games]
        if not results and record:
            # Parse record string like "5-4-1" to build dots
            parts = record.replace("–", "-").split("-")
            if len(parts) == 3:
                try:
                    w, losses_n, otl = (int(x) for x in parts)
                    results = (["W"] * w + ["L"] * losses_n + ["OTL"] * otl)[:10]
                except ValueError:
                    pass

        dots_html = ""
        if results:
            # 10px dots + 3px gaps keep the row ~130px so it fits a half-width cell on phones
            dot_cells = "".join(
                f'<td style="{"padding-right:3px;" if i < len(results) - 1 else ""}">'
                f'<div style="width:10px;height:10px;background:{dot_colors.get(res, "#bbb")};'
                f'border-radius:5px;line-height:10px;font-size:0;">&nbsp;</div></td>'
                for i, res in enumerate(results)
            )
            dots_html = (
                f'<table role="presentation" cellpadding="0" cellspacing="0" border="0" style="margin-top:10px;">'
                f"<tr>{dot_cells}</tr>"
                f"</table>"
            )

        form_cell = (
            f'<td width="50%" valign="top" style="padding:14px;background:#f8f9fb;">'
            f'<div style="font-family:{FONT_DATA};font-size:10px;font-weight:700;letter-spacing:2px;color:#718096;text-transform:uppercase;">Last 10</div>'
            f'<div class="od-big" style="font-family:{FONT_EDITORIAL};font-size:30px;font-weight:800;color:#191c1e;letter-spacing:-1px;margin-top:8px;line-height:1;white-space:nowrap;">{record}</div>'
            f"{dots_html}"
            f"</td>"
        )
    else:
        form_cell = '<td width="50%" style="background:#f8f9fb;"></td>'

    return f"""
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
           style="background:#ffffff;border-radius:12px;overflow:hidden;">
      <tr><td style="padding:28px 28px 8px 28px;">
        {_section_marker("Series · Form")}
      </td></tr>
      <tr><td style="padding:18px 28px 24px 28px;">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
          <tr>
            {series_cell}
            {form_cell}
          </tr>
        </table>
      </td></tr>
    </table>
    """


def _build_suffer_o_meter_html(suffer_score: dict) -> str:
    """Build the Suffer-O-Meter visual bar card.

    Args:
        suffer_score: Dict with score (1-10), label, and color from scheduler.

    Returns:
        HTML string for the Suffer-O-Meter card, or empty string if no data.
    """
    if not suffer_score:
        return ""

    score = suffer_score.get("score", 5)
    label = suffer_score.get("label", "")
    chip_bg = suffer_score.get("color") or C_SECONDARY
    reasons = " · ".join(suffer_score.get("reasons") or [])
    reasons_html = (
        f'<div style="font-family:{FONT_DATA};font-size:12px;font-weight:600;color:{C_MID_BLUE};margin-top:4px;">{esc(reasons)}</div>'
        if reasons
        else ""
    )

    # Colour ramp per the design spec
    RAMP = [
        "#2e7d32",
        "#5b9b3e",
        "#88b94a",
        "#c8c150",
        "#e8a93a",
        "#e88a2a",
        "#d53e00",
        "#c62828",
        "#b71c1c",
        "#7f0000",
    ]
    UNFILLED = "#e6dee0"

    gauge_cells = ""
    for i in range(1, 11):
        idx = i - 1
        is_active = i == score
        is_filled = i <= score
        color = RAMP[idx] if is_filled else UNFILLED
        pad = "padding-right:3px;" if i < 10 else ""
        if is_active:
            cell_div = f'<div style="height:14px;background:{color};border-radius:6px;line-height:14px;font-size:0;border:2px solid #000616;">&nbsp;</div>'
        else:
            cell_div = f'<div style="height:10px;background:{color};border-radius:6px;line-height:10px;font-size:0;">&nbsp;</div>'
        gauge_cells += f'<td width="10%" style="{pad}">{cell_div}</td>'

    # Mood badge
    if score <= 2:
        badge_label = "Bliss"
    elif score <= 4:
        badge_label = "Fine"
    elif score <= 6:
        badge_label = "Meh"
    elif score <= 9:
        badge_label = "Suffering"
    else:
        badge_label = "Despair"

    return f"""
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
           style="background:#ffffff;border-radius:12px;overflow:hidden;">
      <tr><td style="padding:24px 28px 8px 28px;">
        {_section_marker("Suffer-O-Meter")}
      </td></tr>
      <tr><td style="padding:14px 28px 8px 28px;">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
          <tr>
            <td valign="middle">
              <div style="font-family:{FONT_EDITORIAL};font-size:64px;font-weight:800;color:#191c1e;line-height:1;letter-spacing:-2px;">{score}<span style="font-size:24px;color:#718096;font-weight:600;letter-spacing:0;">/10</span></div>
              <div style="font-family:{FONT_DATA};font-size:13px;font-weight:600;color:#4a5568;margin-top:6px;">{label}</div>
              {reasons_html}
            </td>
            <td valign="middle" align="right" width="44">
              <div style="display:inline-block;padding:8px 14px;background:{chip_bg};border-radius:3px;font-family:{FONT_DATA};font-size:11px;font-weight:700;letter-spacing:2px;color:#ffffff;text-transform:uppercase;">{badge_label}</div>
            </td>
          </tr>
        </table>
      </td></tr>
      <tr><td style="padding:14px 28px 24px 28px;">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
          <tr>{gauge_cells}</tr>
          <tr>
            <td colspan="10" style="padding-top:8px;">
              <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
                <tr>
                  <td align="left" style="font-family:{FONT_DATA};font-size:10px;font-weight:600;color:#718096;letter-spacing:1.5px;text-transform:uppercase;">Bliss</td>
                  <td align="center" style="font-family:{FONT_DATA};font-size:10px;font-weight:600;color:#718096;letter-spacing:1.5px;text-transform:uppercase;">Annoyed</td>
                  <td align="right" style="font-family:{FONT_DATA};font-size:10px;font-weight:600;color:#718096;letter-spacing:1.5px;text-transform:uppercase;">Despair</td>
                </tr>
              </table>
            </td>
          </tr>
        </table>
      </td></tr>
    </table>
    """
