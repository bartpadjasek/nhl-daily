"""NHL advanced stats fetcher for the NHL Daily digest.

Fetches season-level 5-on-5 analytics from the official NHL stats API
(no authentication required). Previously used MoneyPuck, but that site
is behind Cloudflare bot protection. The NHL percentages endpoint provides
equivalent Corsi, Fenwick, and PDO metrics.
"""

import logging
import unicodedata
from datetime import UTC, datetime

import requests

from config import TEAM

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 10


def _plain(name: str) -> str:
    """'Montréal Canadiens' → 'montreal canadiens' (the stats API uses accents)."""
    decomposed = unicodedata.normalize("NFKD", name)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).casefold()


def _current_season_id() -> int:
    """Return the NHL season ID for the current season, e.g. 20252026.

    The season ID is formed as YYYYYYYY where the first four digits are the
    start year and the last four are the end year. The season starts in October,
    so months before August belong to the previous season.
    """
    now = datetime.now(UTC)
    start_year = now.year if now.month >= 8 else now.year - 1
    return int(f"{start_year}{start_year + 1}")


def fetch_team_advanced_stats() -> dict | None:
    """Fetch the configured team's 5-on-5 advanced stats from the NHL stats API.

    Returns season-to-date Corsi%, Fenwick%, PDO, and 5v5 save percentage.
    All percentage values are returned as floats rounded to one decimal place.

    Returns:
        Dict with keys:
            corsi_pct   — Corsi For % (shot attempts, 5v5), e.g. 53.9
            fenwick_pct — Fenwick For % (unblocked shot attempts, 5v5), e.g. 54.3
            pdo         — PDO (shooting% + save%, 5v5 combined luck indicator), e.g. 98.3
            sv_pct_5v5  — Save percentage at 5v5, e.g. 90.3
        Or None if data is unavailable or parsing fails.
    """
    try:
        season_id = _current_season_id()
        url = (
            "https://api.nhle.com/stats/rest/en/team/percentages"
            f"?cayenneExp=gameTypeId=2 and seasonId<={season_id} and seasonId>={season_id}"
        )
        resp = requests.get(
            url,
            timeout=REQUEST_TIMEOUT,
            headers={"User-Agent": "NHLDaily/1.0"},
        )
        resp.raise_for_status()
        data = resp.json().get("data", [])
    except Exception as e:
        logger.warning("NHL advanced stats fetch failed: %s", e)
        return None

    try:
        ours = next(
            (t for t in data if _plain(t.get("teamFullName", "")) == _plain(TEAM.name)), None
        )
        if not ours:
            logger.warning("NHL advanced stats: %s not found in response", TEAM.name)
            return None

        result = {
            "corsi_pct": round(ours["satPct"] * 100, 1),
            "fenwick_pct": round(ours["usatPct"] * 100, 1),
            "pdo": round(ours["shootingPlusSavePct5v5"] * 100, 1),
            "sv_pct_5v5": round(ours["savePct5v5"] * 100, 1),
        }
        logger.info("NHL advanced stats: %s", result)
        return result

    except Exception as e:
        logger.warning("NHL advanced stats parse error: %s", e)
        return None
