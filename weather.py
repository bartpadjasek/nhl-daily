"""OpenWeatherMap fetcher for road game weather context.

Fetches current weather for the opponent's city on road trips only.
Always uses metric units (°C). Requires OPENWEATHERMAP_API_KEY in the environment.
"""

import logging
import os

import requests
from dotenv import load_dotenv

from config import TEAM

load_dotenv()

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 10

# Mapping of NHL team abbreviations to their arena cities
NHL_CITIES: dict[str, str] = {
    "ANA": "Anaheim",
    "BOS": "Boston",
    "BUF": "Buffalo",
    "CAR": "Raleigh",
    "CBJ": "Columbus",
    "CGY": "Calgary",
    "CHI": "Chicago",
    "COL": "Denver",
    "DAL": "Dallas",
    "DET": "Detroit",
    "FLA": "Sunrise",
    "LAK": "Los Angeles",
    "MIN": "Saint Paul",
    "MTL": "Montreal",
    "NSH": "Nashville",
    "NJD": "Newark",
    "NYI": "Elmont",
    "NYR": "New York",
    "OTT": "Ottawa",
    "PHI": "Philadelphia",
    "PIT": "Pittsburgh",
    "SEA": "Seattle",
    "SJS": "San Jose",
    "STL": "Saint Louis",
    "TBL": "Tampa",
    "TOR": "Toronto",
    "UTA": "Salt Lake City",
    "VAN": "Vancouver",
    "VGK": "Las Vegas",
    "WSH": "Washington",
    "WPG": "Winnipeg",
}


def fetch_game_weather(opponent_abbrev: str, home_or_away: str) -> dict | None:
    """Fetch current weather for the game venue.

    For home games, returns the home city's weather. For away games, returns the
    opponent's city weather. Temperature is always in Celsius. Returns None
    silently if the API key is not set, the city is unknown, or the request fails.

    Args:
        opponent_abbrev: NHL team abbreviation, e.g. "DAL" or "CGY".
        home_or_away: "home" or "away".

    Returns:
        Dict with keys:
            city        — City name string, e.g. "Dallas"
            temp_c      — Current temperature in °C (float, 1 decimal)
            condition   — Short condition label, e.g. "Clear"
            description — Longer description, e.g. "clear sky"
        Or None if unavailable.
    """
    api_key = os.environ.get("OPENWEATHERMAP_API_KEY")
    if not api_key:
        return None

    if home_or_away == "home":
        city = NHL_CITIES.get(TEAM.abbrev, TEAM.place)
    else:
        city = NHL_CITIES.get(opponent_abbrev)
        if not city:
            logger.warning("Weather: no city mapping for team %s", opponent_abbrev)
            return None

    try:
        resp = requests.get(
            "https://api.openweathermap.org/data/2.5/weather",
            params={"q": city, "units": "metric", "appid": api_key},
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()

        temp_c = round(data["main"]["temp"], 1)
        condition = data["weather"][0]["main"]
        description = data["weather"][0]["description"]

        result = {
            "city": city,
            "temp_c": temp_c,
            "condition": condition,
            "description": description,
        }
        logger.info("Weather for %s (%s): %s°C, %s", opponent_abbrev, city, temp_c, description)
        return result

    except Exception as e:
        logger.warning("Weather fetch failed for %s: %s", opponent_abbrev, e)
        return None
