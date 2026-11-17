"""Playoff cards: the bracket and our team' series view."""

from emailer.theme import (
    ABBR,
    C_MID_BLUE,
    C_ON_SURFACE,
    C_ON_SURFACE_MUTED,
    C_PRIMARY_CONT,
    C_SECONDARY_CONT,
    C_SURFACE_LOW,
    C_SURFACE_LOWEST,
    C_WIN,
    FONT_DATA,
    FONT_EDITORIAL,
    NICK,
    OTHER_CONF_SHORT,
    PLACE,
    _section_marker,
)

# ---------------------------------------------------------------------------
# Playoff bracket structure
# ---------------------------------------------------------------------------
# Each frozenset is a pair of R1 series letters whose winners meet in Round 2.
# Standard NHL format: A+B, C+D (East); E+F, G+H (West).
_R1_BRACKET_PAIRS: list[frozenset[str]] = [
    frozenset("AB"),
    frozenset("CD"),
    frozenset("EF"),
    frozenset("GH"),
]


_EAST_R1_LETTERS = frozenset("ABCD")


_WEST_R1_LETTERS = frozenset("EFGH")


def _build_playoff_bracket_html(bracket: dict) -> str:
    """Build the playoff bracket section.

    Renders an "Path to the Cup" flow at the top (R1→R2→CF→SCF),
    then R1 as bracket pods (pairs of series whose winners meet in R2),
    followed by later rounds as teams are determined.

    Args:
        bracket: The playoff_bracket dict from nhl._extract_playoff_bracket().

    Returns:
        HTML string for the bracket section, or empty string if no data.
    """
    if not bracket:
        return ""

    rounds = bracket.get("rounds", [])
    if not rounds:
        return ""

    # ------------------------------------------------------------------ helpers

    _empty_pip = (
        '<span style="display:inline-block;width:9px;height:9px;border-radius:50%;'
        'border:1.5px solid #ccc;margin:0 2px;vertical-align:middle;"></span>'
    )

    def _filled_pip(color: str) -> str:
        return (
            f'<span style="display:inline-block;width:9px;height:9px;border-radius:50%;'
            f'background:{color};margin:0 2px;vertical-align:middle;"></span>'
        )

    def _matchup_card(s: dict, is_scf: bool = False) -> str:
        top, bottom = s["top_seed"], s["bottom_seed"]
        top_w, bottom_w = s["top_wins"], s["bottom_wins"]
        winner = s.get("winner")
        involves_us = s.get("involves_us", False)
        letter = s.get("letter", "")
        status = s.get("series_status", "")

        card_border = (
            f"border-left:4px solid {C_SECONDARY_CONT};"
            if involves_us
            else "border-left:4px solid transparent;"
        )
        card_bg = "#fff8f3" if involves_us else C_SURFACE_LOWEST
        abbrev_size = "15px" if is_scf else "14px"

        def _team_row(abbrev: str, wins: int, is_winner: bool, is_loser: bool) -> str:
            if is_winner:
                ns = f"font-weight:800;color:{C_PRIMARY_CONT};font-size:{abbrev_size};"
                pc = C_PRIMARY_CONT
            elif is_loser:
                ns = f"font-weight:500;color:{C_ON_SURFACE_MUTED};font-size:{abbrev_size};"
                pc = "#bbb"
            else:
                ns = f"font-weight:700;color:{C_ON_SURFACE};font-size:{abbrev_size};"
                pc = C_PRIMARY_CONT
            pips = "".join(_filled_pip(pc) if i < wins else _empty_pip for i in range(4))
            return (
                f'<tr><td style="padding:8px 12px 4px;{ns}font-family:{FONT_DATA};">{abbrev}</td>'
                f'<td style="padding:8px 12px 4px;text-align:right;white-space:nowrap;">{pips}</td></tr>'
            )

        top_is_winner = winner == top
        top_is_loser = winner is not None and winner == bottom
        bottom_is_winner = winner == bottom
        bottom_is_loser = winner is not None and winner == top
        header = (
            "&#127942; Stanley Cup Final"
            if is_scf
            else (f"Series {letter}" if letter else "Series")
        )
        divider = (
            '<tr><td colspan="2" style="padding:0 12px;">'
            '<div style="height:1px;background:#eee;"></div></td></tr>'
        )
        status_html = (
            (
                f'<tr><td colspan="2" style="padding:4px 12px 10px;font-size:11px;'
                f"font-weight:{'700' if winner else '500'};"
                f"color:{C_WIN if winner else C_ON_SURFACE_MUTED};"
                f'font-style:{"normal" if winner else "italic"};">{status}</td></tr>'
            )
            if status
            else '<tr><td colspan="2" style="padding:4px 12px 10px;"></td></tr>'
        )

        return (
            f'<div style="background:{card_bg};border-radius:8px;{card_border}'
            f'overflow:hidden;margin-bottom:8px;">'
            f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">'
            f'<tr><td colspan="2" style="padding:8px 12px 4px;font-size:10px;font-weight:700;'
            f"letter-spacing:1.2px;color:{C_ON_SURFACE_MUTED};text-transform:uppercase;"
            f'font-family:{FONT_DATA};">{header}</td></tr>'
            f"{_team_row(top, top_w, top_is_winner, top_is_loser)}"
            f"{divider}"
            f"{_team_row(bottom, bottom_w, bottom_is_winner, bottom_is_loser)}"
            f"{status_html}"
            f"</table></div>"
        )

    # ------------------------------------------------------------------ data setup

    r1_round = next((r for r in rounds if r["round"] == 1), None)
    r1_series = r1_round["series"] if r1_round else []
    series_by_letter = {s["letter"]: s for s in r1_series}

    # Identify which round we are currently in
    our_current_round = 0
    for rnd in rounds:
        for s in rnd.get("series", []):
            if s.get("involves_us"):
                our_current_round = rnd["round"]

    # R1 bracket path analysis
    our_r1 = next((s for s in r1_series if s.get("involves_us")), None)
    our_letter = our_r1["letter"] if our_r1 else None
    r2_partner: dict | None = None
    cf_teams: list[str] = []

    if our_letter:
        our_conf = _EAST_R1_LETTERS if our_letter in _EAST_R1_LETTERS else _WEST_R1_LETTERS
        our_pair = next((p for p in _R1_BRACKET_PAIRS if our_letter in p), None)
        if our_pair:
            partner_letter = next((lt for lt in sorted(our_pair) if lt != our_letter), None)
            r2_partner = series_by_letter.get(partner_letter)
        for pair in _R1_BRACKET_PAIRS:
            if our_letter not in pair and pair & our_conf:
                for letter in sorted(pair):
                    s = series_by_letter.get(letter)
                    if s:
                        cf_teams += [s["top_seed"], s["bottom_seed"]]

    # ------------------------------------------------------------------ path section

    path_html = ""
    if our_r1 and r2_partner:
        our_r1_opp = our_r1["bottom_seed"] if our_r1["top_seed"] == ABBR else our_r1["top_seed"]
        r2_opp_str = f"{r2_partner['top_seed']} or {r2_partner['bottom_seed']}"
        cf_str = " / ".join(cf_teams) if cf_teams else "TBD"

        def _path_step(
            round_label: str, line1: str, line2: str, is_active: bool, is_us: bool
        ) -> str:
            bg = (
                "#fff4ef"
                if is_us and is_active
                else (C_SURFACE_LOW if is_active else C_SURFACE_LOWEST)
            )
            border_color = (
                C_SECONDARY_CONT if is_us and is_active else ("#c5d0dc" if is_active else "#e8ecf0")
            )
            label_color = C_SECONDARY_CONT if is_us and is_active else C_ON_SURFACE_MUTED
            text_color = C_PRIMARY_CONT if is_active else C_ON_SURFACE_MUTED
            return (
                f'<td style="padding:10px 6px;text-align:center;vertical-align:top;'
                f'background:{bg};border:2px solid {border_color};border-radius:8px;">'
                f'<div style="font-size:9px;font-weight:700;letter-spacing:1.1px;'
                f"text-transform:uppercase;color:{label_color};font-family:{FONT_DATA};"
                f'margin-bottom:5px;">{round_label}</div>'
                f'<div style="font-size:12px;font-weight:700;color:{text_color};'
                f'font-family:{FONT_DATA};line-height:1.3;">{line1}</div>'
                f'<div style="font-size:10px;font-weight:500;color:{C_ON_SURFACE_MUTED};'
                f'font-family:{FONT_DATA};margin-top:2px;">{line2}</div>'
                f"</td>"
            )

        arrow = (
            '<td style="padding:0 3px;text-align:center;vertical-align:middle;'
            'color:#c5d0dc;font-size:18px;font-weight:300;">&#8250;</td>'
        )

        path_html = f"""
        <div style="margin-bottom:18px;">
          <p style="margin:0 0 8px;font-size:10px;font-weight:700;letter-spacing:1.2px;
                    text-transform:uppercase;color:{C_ON_SURFACE_MUTED};font-family:{FONT_DATA};">
            {NICK}&#8217; path to the cup</p>
          <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
            <tr>
              {_path_step("Round 1", f"vs {our_r1_opp}", "", our_current_round == 1, True)}
              {arrow}
              {_path_step("Round 2", f"vs {r2_opp_str}", "if we advance", our_current_round == 2, our_current_round == 2)}
              {arrow}
              {_path_step("Conf. Final", f"vs {cf_str}", "winner", our_current_round == 3, our_current_round == 3)}
              {arrow}
              {_path_step("Stanley Cup", f"vs {OTHER_CONF_SHORT}", "finalist", our_current_round == 4, our_current_round == 4)}
            </tr>
          </table>
        </div>
        """

    # ------------------------------------------------------------------ R1 pods

    r1_pods_html = ""
    if r1_series:
        pod_groups: list[list[dict]] = []
        for pair in _R1_BRACKET_PAIRS:
            pod = [series_by_letter[lt] for lt in sorted(pair) if lt in series_by_letter]
            if pod:
                pod_groups.append(pod)

        # Lay out 2 pods per row (East row, then West row)
        pod_rows = [pod_groups[i : i + 2] for i in range(0, len(pod_groups), 2)]
        for row in pod_rows:
            cells = ""
            for pod in row:
                has_us = any(s.get("involves_us") for s in pod)
                pod_bg = "#fff4ef" if has_us else C_SURFACE_LOW
                pod_border = (
                    f"border:1.5px solid {C_SECONDARY_CONT};"
                    if has_us
                    else "border:1.5px solid #e8ecf0;"
                )
                cards_html = "".join(_matchup_card(s) for s in pod)
                if len(pod) == 2:
                    meet_note = (
                        f'<div style="font-size:10px;color:{C_ON_SURFACE_MUTED};'
                        f'text-align:center;padding:4px 0 6px;font-family:{FONT_DATA};">'
                        f"&#8595; winners meet in Round 2</div>"
                    )
                else:
                    meet_note = ""
                cells += (
                    f'<td width="50%" style="padding:4px;">'
                    f'<div style="background:{pod_bg};{pod_border}border-radius:10px;padding:8px 8px 0;">'
                    f"{cards_html}{meet_note}"
                    f"</div></td>"
                )
            r1_pods_html += (
                f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"'
                f' style="margin-bottom:8px;"><tr valign="top">{cells}</tr></table>'
            )

    # ------------------------------------------------------------------ later rounds

    later_html = ""
    for rnd in rounds:
        if rnd["round"] == 1:
            continue
        round_num = rnd["round"]
        round_name = rnd["name"]
        series = rnd.get("series", [])
        if not series:
            continue

        round_label = (
            f'<p style="margin:16px 0 8px;font-size:12px;font-weight:700;letter-spacing:1px;'
            f'color:{C_PRIMARY_CONT};text-transform:uppercase;font-family:{FONT_DATA};">'
            f"{round_name}</p>"
        )
        if round_num == 4:
            later_html += round_label + _matchup_card(series[0], is_scf=True)
        else:
            mid = max(1, len(series) // 2)
            left_cards = "".join(_matchup_card(s) for s in series[:mid])
            right_cards = "".join(_matchup_card(s) for s in series[mid:])
            later_html += (
                f"{round_label}"
                f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"'
                f' style="margin-bottom:4px;"><tr valign="top">'
                f'<td width="50%" style="padding-right:6px;">{left_cards}</td>'
                f'<td width="50%" style="padding-left:6px;">{right_cards}</td>'
                f"</tr></table>"
            )

    return f"""
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
           style="background:{C_SURFACE_LOWEST};border-radius:12px;margin-bottom:16px;">
      <tr>
        <td style="padding:24px 24px 16px;">
          <p style="margin:0 0 16px;font-size:11px;font-weight:600;letter-spacing:1.5px;
                    color:{C_ON_SURFACE_MUTED};text-transform:uppercase;">Stanley Cup Playoffs</p>
          {path_html}
          <p style="margin:0 0 8px;font-size:12px;font-weight:700;letter-spacing:1px;
                    color:{C_PRIMARY_CONT};text-transform:uppercase;font-family:{FONT_DATA};">First Round</p>
          {r1_pods_html}
          {later_html}
        </td>
      </tr>
    </table>
    """


def _build_playoff_series_view_html(bracket: dict) -> str:
    """Build the playoff series record display for the current series involving our team.

    Shows the win counts for both teams in a score-style layout with team
    logos, series status, and round name.

    Args:
        bracket: The playoff_bracket dict from nhl.get_team_data().

    Returns:
        HTML string, or empty string if no series involving our team found.
    """
    our_series = None
    round_name = ""
    for round_dict in bracket.get("rounds", []):
        for series in round_dict.get("series", []):
            if series.get("involves_us"):
                our_series = series
                round_name = round_dict.get("name", "")

    if not our_series:
        return ""

    top = our_series.get("top_seed", "")
    bottom = our_series.get("bottom_seed", "")
    top_wins = our_series.get("top_wins", 0)
    bottom_wins = our_series.get("bottom_wins", 0)

    we_are_top = top == ABBR
    our_wins = top_wins if we_are_top else bottom_wins
    opp_abbrev = bottom if we_are_top else top
    opp_wins = bottom_wins if we_are_top else top_wins

    series_status = our_series.get("series_status", "")
    games_played = our_wins + opp_wins

    opp_logo_url = f"https://assets.nhle.com/logos/nhl/svg/{opp_abbrev}_light.svg"
    our_logo_url = f"https://assets.nhle.com/logos/nhl/svg/{ABBR}_light.svg"

    round_label = f"{round_name} · Game {games_played}" if round_name else f"Game {games_played}"

    return f"""
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
           style="background:#ffffff;border-radius:12px;overflow:hidden;">
      <tr><td style="padding:28px 28px 8px 28px;">
        {_section_marker("Playoff Series")}
      </td></tr>
      <tr><td style="padding:18px 28px 26px 28px;">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
          <tr>
            <td valign="middle" width="40%">
              <img src="{our_logo_url}" width="36" alt="{ABBR}" style="display:block;width:36px;height:auto;border:0;margin-bottom:8px;">
              <div style="font-family:{FONT_DATA};font-size:11px;font-weight:700;letter-spacing:2px;color:{C_MID_BLUE};text-transform:uppercase;">{PLACE}</div>
              <div style="font-family:{FONT_EDITORIAL};font-size:52px;font-weight:800;color:#041e42;line-height:1;letter-spacing:-2px;margin-top:4px;">{our_wins}</div>
            </td>
            <td valign="middle" width="20%" align="center">
              <div style="font-family:{FONT_EDITORIAL};font-size:24px;font-weight:800;color:#cbd2dc;">–</div>
              <div style="font-family:{FONT_DATA};font-size:10px;font-weight:700;letter-spacing:1.5px;color:{C_MID_BLUE};text-transform:uppercase;margin-top:6px;">wins to<br>advance</div>
            </td>
            <td valign="middle" width="40%" align="right">
              <img src="{opp_logo_url}" width="36" alt="{opp_abbrev}" style="display:block;width:36px;height:auto;border:0;margin-bottom:8px;margin-left:auto;">
              <div style="font-family:{FONT_DATA};font-size:11px;font-weight:700;letter-spacing:2px;color:{C_MID_BLUE};text-transform:uppercase;">{opp_abbrev}</div>
              <div style="font-family:{FONT_EDITORIAL};font-size:52px;font-weight:800;color:{C_MID_BLUE};line-height:1;letter-spacing:-2px;margin-top:4px;">{opp_wins}</div>
            </td>
          </tr>
        </table>
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="margin-top:16px;">
          <tr><td style="border-top:1px solid #e6eaf0;padding-top:12px;">
            <div style="font-family:{FONT_DATA};font-size:12px;font-weight:600;color:{C_MID_BLUE};">{series_status}</div>
            <div style="font-family:{FONT_DATA};font-size:11px;color:#718096;margin-top:2px;">{round_label}</div>
          </td></tr>
        </table>
      </td></tr>
    </table>
    """
