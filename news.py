"""Google News RSS fetcher for current team headlines.

Fetches recent news headlines silently — they are injected into the model prompts
to improve writing quality and contextual awareness, but never shown in the email.
No API key required.
"""

import logging
import xml.etree.ElementTree as ET

import requests

from config import TEAM

logger = logging.getLogger(__name__)

RSS_BASE = "https://news.google.com/rss/search"
REQUEST_TIMEOUT = 10


def _fetch_rss_headlines(query: str, n: int) -> list[str]:
    """Fetch headlines from Google News RSS for the given search query.

    Args:
        query: Search query string.
        n: Maximum number of headlines to return.

    Returns:
        List of headline strings. Empty list on any error.
    """
    try:
        url = f"{RSS_BASE}?q={requests.utils.quote(query)}&hl=en-CA&gl=CA&ceid=CA:en"
        resp = requests.get(
            url,
            timeout=REQUEST_TIMEOUT,
            headers={"User-Agent": "NHLDaily/1.0"},
        )
        resp.raise_for_status()

        root = ET.fromstring(resp.content)
        channel = root.find("channel")
        if channel is None:
            return []

        headlines = []
        for item in channel.findall("item"):
            title_el = item.find("title")
            if title_el is not None and title_el.text:
                # Strip source suffix Google appends: "Headline - Source Name"
                title = title_el.text.rsplit(" - ", 1)[0].strip()
                if title:
                    headlines.append(title)
            if len(headlines) >= n:
                break

        return headlines

    except Exception as e:
        logger.warning("Could not fetch RSS headlines for %r: %s", query, e)
        return []


def fetch_team_headlines(n: int = 6) -> list[str]:
    """Fetch recent news headlines about the configured team from Google News RSS.

    Used to give the model awareness of current events (injuries, trades, lineup
    changes, criticism) that it cannot know from stats alone. Headlines are
    passed to the model as context only — they are not shown in the email.

    Args:
        n: Maximum number of headlines to return.

    Returns:
        List of headline strings. Empty list on any error so the pipeline
        continues without news context.
    """
    headlines = _fetch_rss_headlines(f"{TEAM.name} NHL", n)
    logger.info("Fetched %d %s headlines from Google News", len(headlines), TEAM.nickname)
    return headlines


def fetch_opponent_goalie_news(team_name: str, n: int = 8) -> list[str]:
    """Search for goalie start news for the opposing team.

    Used to detect likely starters beyond the default most-GP heuristic.
    Headlines are never shown in the email.

    Args:
        team_name: Full team name, e.g. "Seattle Kraken".
        n: Maximum number of headlines to return.

    Returns:
        List of headline strings. Empty list on any error.
    """
    headlines = _fetch_rss_headlines(f"{team_name} goalie start NHL", n)
    logger.info("Fetched %d goalie headlines for %s", len(headlines), team_name)
    return headlines
