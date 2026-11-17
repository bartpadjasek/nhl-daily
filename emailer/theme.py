"""Shared look of the emails: colour and font constants, small formatting
helpers, the section marker and team logo URLs.
"""

import html
from datetime import datetime

from config import SETTINGS, TEAM
from team import CONFERENCE_NAMES, DIVISION_NAMES

# The configured team (config.toml) and the names used in labels and copy
NEWSLETTER = SETTINGS.newsletter_name  # "NHL Daily"
NAME = TEAM.name  # "Edmonton Oilers"
NICK = TEAM.nickname  # "Oilers"
PLACE = TEAM.place  # "Edmonton"
ABBR = TEAM.abbrev  # "EDM"
DIV = DIVISION_NAMES[TEAM.division]  # "Pacific"
CONF = CONFERENCE_NAMES[TEAM.conference]  # "Western"
CONF_SHORT = "West" if TEAM.conference == "W" else "East"
OTHER_CONF_SHORT = "East" if TEAM.conference == "W" else "West"

RESULT_COLORS = {
    "W": "#2e7d32",
    "L": "#c62828",
    "OTL": "#757575",
}


# ---------------------------------------------------------------------------
# Design tokens
# ---------------------------------------------------------------------------
C_PRIMARY = "#000616"  # Midnight


C_PRIMARY_CONT = "#041e42"  # Primary container


C_SECONDARY = "#aa3000"  # Action orange (use sparingly)


C_SECONDARY_CONT = "#d53e00"  # Orange container (CTAs, accents)


C_SURFACE = "#eceef2"  # The Canvas (body background)


C_SURFACE_LOW = "#f4f6fa"  # Alternate row stripe


C_SURFACE_LOWEST = "#ffffff"  # Content cards


C_ON_SURFACE = "#191c1e"  # The Ink (primary text)


C_ON_SURFACE_MED = "#4a5568"  # Medium text


C_ON_SURFACE_MUTED = "#718096"  # Muted/metadata text


C_ON_PRIMARY = "#ffffff"  # Text on dark backgrounds


C_ON_SECONDARY = "#ffffff"  # Text on orange backgrounds


C_WIN = "#2e7d32"


C_LOSS = "#c62828"


C_OTL = "#757575"


FONT_EDITORIAL = "'Work Sans','Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif"


FONT_DATA = "'Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif"


C_MID_BLUE = "#5d6b85"  # team names, section sub-labels


C_ROW_BORDER = "#eceef2"  # row dividers


C_TEAM_HIGHLIGHT = "#fff4ee"  # EDM row highlight in standings


C_FOOTER_TEXT = "#a3abbd"  # muted text on the C_PRIMARY footer (8.8:1)


C_FINE_PRINT = "#8a93a8"  # fine print on the C_PRIMARY footer (6.6:1)


def divisions_ours_first(conference_standings: dict) -> list[tuple[str, list]]:
    """(division name, teams) pairs with the division that contains us first."""
    return sorted(
        conference_standings.items(),
        key=lambda item: 0 if any(t.get("is_us") for t in item[1]) else 1,
    )


def esc(value) -> str:
    """The one way outside text enters the email HTML.

    Use it for anything from the model, Wikipedia, ESPN, the NHL API or
    the weather API, in text or in a double-quoted attribute (href, alt).
    Escapes &, <, > and "; apostrophes are left as they are, which is safe in
    both places because every attribute in these emails uses double quotes.
    """
    return html.escape(str(value), quote=False).replace('"', "&quot;")


def _format_date(date_str: str) -> str:
    """Format a YYYY-MM-DD date string as "Month D, YYYY", e.g. "March 28, 2026".

    Args:
        date_str: ISO date string, e.g. "2026-03-28".

    Returns:
        Human-readable date string, or the original string on parse failure.
    """
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        return f"{dt.strftime('%B')} {dt.day}, {dt.year}"
    except (ValueError, TypeError):
        return date_str or ""


def _result_label(result: str) -> str:
    """Return a human-readable result label.

    Args:
        result: One of "W", "L", or "OTL".

    Returns:
        Display string, e.g. "WIN", "LOSS", "OT LOSS".
    """
    return {"W": "WIN", "L": "LOSS", "OTL": "OT LOSS"}.get(result, result)


def _save_pct_display(pct: float) -> str:
    """Format a save percentage float as a readable string like .923.

    Args:
        pct: Save percentage as a float, e.g. 0.923.

    Returns:
        Formatted string, e.g. ".923".
    """
    if not pct:
        return "N/A"
    return f"{pct:.3f}".lstrip("0") or ".000"


def _team_logo_url(abbrev: str, variant: str = "light") -> str:
    """Build the NHL CDN URL for a team's logo SVG.

    Args:
        abbrev: Team abbreviation, e.g. "EDM", "VAN".
        variant: "light" for use on light backgrounds (the NHL's naming refers to
            the background), "dark" for dark backgrounds.

    Returns:
        Full URL string to the team logo SVG.
    """
    return f"https://assets.nhle.com/logos/nhl/svg/{abbrev}_{variant}.svg"


def _rank_suffix(rank: int) -> str:
    """Return ordinal suffix for a division rank number.

    Args:
        rank: Integer rank, e.g. 1, 2, 3.

    Returns:
        Suffix string: "st", "nd", "rd", or "th".
    """
    return {1: "st", 2: "nd", 3: "rd"}.get(rank, "th")


def _section_marker(label: str) -> str:
    return (
        f'<table role="presentation" cellpadding="0" cellspacing="0" border="0">'
        f'<tr><td style="border-left:3px solid {C_SECONDARY_CONT};padding-left:12px;'
        f"font-family:{FONT_DATA};font-size:11px;font-weight:700;letter-spacing:2.5px;"
        f'color:{C_ON_SURFACE};text-transform:uppercase;line-height:1.2;">{label}</td></tr>'
        f"</table>"
    )
