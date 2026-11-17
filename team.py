"""Static facts about every NHL team: names, home time zone, division and conference.

Divisions and conferences are also read live from the standings API where it
matters (standings, playoff race); this table is the fallback and the source
for names and time zones. Update it if the league realigns or a team moves.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Team:
    abbrev: str  # NHL API abbreviation, e.g. "EDM"
    name: str  # full name, e.g. "Edmonton Oilers"
    nickname: str  # e.g. "Oilers"
    place: str  # e.g. "Edmonton"
    timezone: str  # IANA zone of the home arena
    division: str  # "A", "M", "C" or "P"
    conference: str  # "E" or "W"


DIVISION_NAMES = {"A": "Atlantic", "M": "Metropolitan", "C": "Central", "P": "Pacific"}
CONFERENCE_NAMES = {"E": "Eastern", "W": "Western"}

_ROWS = [
    # abbrev, name, nickname, place, timezone, division, conference
    ("ANA", "Anaheim Ducks", "Ducks", "Anaheim", "America/Los_Angeles", "P", "W"),
    ("BOS", "Boston Bruins", "Bruins", "Boston", "America/New_York", "A", "E"),
    ("BUF", "Buffalo Sabres", "Sabres", "Buffalo", "America/New_York", "A", "E"),
    ("CGY", "Calgary Flames", "Flames", "Calgary", "America/Edmonton", "P", "W"),
    ("CAR", "Carolina Hurricanes", "Hurricanes", "Carolina", "America/New_York", "M", "E"),
    ("CHI", "Chicago Blackhawks", "Blackhawks", "Chicago", "America/Chicago", "C", "W"),
    ("COL", "Colorado Avalanche", "Avalanche", "Colorado", "America/Denver", "C", "W"),
    ("CBJ", "Columbus Blue Jackets", "Blue Jackets", "Columbus", "America/New_York", "M", "E"),
    ("DAL", "Dallas Stars", "Stars", "Dallas", "America/Chicago", "C", "W"),
    ("DET", "Detroit Red Wings", "Red Wings", "Detroit", "America/Detroit", "A", "E"),
    ("EDM", "Edmonton Oilers", "Oilers", "Edmonton", "America/Edmonton", "P", "W"),
    ("FLA", "Florida Panthers", "Panthers", "Florida", "America/New_York", "A", "E"),
    ("LAK", "Los Angeles Kings", "Kings", "Los Angeles", "America/Los_Angeles", "P", "W"),
    ("MIN", "Minnesota Wild", "Wild", "Minnesota", "America/Chicago", "C", "W"),
    ("MTL", "Montreal Canadiens", "Canadiens", "Montreal", "America/Toronto", "A", "E"),
    ("NSH", "Nashville Predators", "Predators", "Nashville", "America/Chicago", "C", "W"),
    ("NJD", "New Jersey Devils", "Devils", "New Jersey", "America/New_York", "M", "E"),
    ("NYI", "New York Islanders", "Islanders", "New York", "America/New_York", "M", "E"),
    ("NYR", "New York Rangers", "Rangers", "New York", "America/New_York", "M", "E"),
    ("OTT", "Ottawa Senators", "Senators", "Ottawa", "America/Toronto", "A", "E"),
    ("PHI", "Philadelphia Flyers", "Flyers", "Philadelphia", "America/New_York", "M", "E"),
    ("PIT", "Pittsburgh Penguins", "Penguins", "Pittsburgh", "America/New_York", "M", "E"),
    ("SJS", "San Jose Sharks", "Sharks", "San Jose", "America/Los_Angeles", "P", "W"),
    ("SEA", "Seattle Kraken", "Kraken", "Seattle", "America/Los_Angeles", "P", "W"),
    ("STL", "St. Louis Blues", "Blues", "St. Louis", "America/Chicago", "C", "W"),
    ("TBL", "Tampa Bay Lightning", "Lightning", "Tampa Bay", "America/New_York", "A", "E"),
    ("TOR", "Toronto Maple Leafs", "Maple Leafs", "Toronto", "America/Toronto", "A", "E"),
    ("UTA", "Utah Mammoth", "Mammoth", "Utah", "America/Denver", "C", "W"),
    ("VAN", "Vancouver Canucks", "Canucks", "Vancouver", "America/Vancouver", "P", "W"),
    ("VGK", "Vegas Golden Knights", "Golden Knights", "Vegas", "America/Los_Angeles", "P", "W"),
    ("WSH", "Washington Capitals", "Capitals", "Washington", "America/New_York", "M", "E"),
    ("WPG", "Winnipeg Jets", "Jets", "Winnipeg", "America/Winnipeg", "C", "W"),
]

TEAMS: dict[str, Team] = {row[0]: Team(*row) for row in _ROWS}


def get_team(abbrev: str) -> Team:
    """The Team for an abbreviation (case-insensitive); ValueError lists the valid ones."""
    key = (abbrev or "").strip().upper()
    if key not in TEAMS:
        raise ValueError(f"Unknown team {abbrev!r}. Use one of: {', '.join(sorted(TEAMS))}")
    return TEAMS[key]
