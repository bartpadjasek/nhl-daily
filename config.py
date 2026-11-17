"""Load config.toml into one Settings object used by every module.

The file path defaults to config.toml next to this module; set NHL_DAILY_CONFIG
to use another (the tests do). Invalid values fail fast with a message that
says which setting to fix.
"""

import os
import tomllib
from dataclasses import dataclass, field
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from team import Team, get_team

DEFAULT_CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.toml")

PROVIDERS = ("anthropic", "openai", "gemini", "openai_compatible")
DEFAULT_MODELS = {
    "anthropic": "claude-opus-5-5",
    "openai": "gpt-4.1",
    "gemini": "gemini-2.5-flash",
    "openai_compatible": "",  # must be set: the model name your server expects
}
API_KEY_ENV = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "openai_compatible": "LLM_API_KEY",
}
CARD_KEYS = (
    "next_up",
    "suffer_o_meter",
    "goal_log",
    "three_stars",
    "series_form",
    "season_5v5",
    "what_we_learned",
    "on_this_day",
    "injuries",
    "standings",
    "playoff_race",
    "team_leaders",
    "player_of_the_week",
    "prospects",
    "coming_up",
)


class ConfigError(ValueError):
    """A setting in config.toml is missing or invalid."""


@dataclass(frozen=True)
class LLMSettings:
    provider: str
    model: str
    base_url: str
    api_key_env: str


@dataclass(frozen=True)
class Settings:
    team: Team
    local_tz: ZoneInfo
    display_tz: ZoneInfo
    llm: LLMSettings
    newsletter_name: str
    from_address: str
    hide_cards: frozenset[str] = field(default_factory=frozenset)
    people: tuple[str, ...] = ()


def _zone(value: str, setting: str) -> ZoneInfo:
    try:
        return ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError) as e:
        raise ConfigError(f"[time] {setting} = {value!r} is not an IANA time zone name") from e


def load_settings(path: str | None = None) -> Settings:
    """Read and validate the config file."""
    path = path or os.environ.get("NHL_DAILY_CONFIG") or DEFAULT_CONFIG_PATH
    try:
        with open(path, "rb") as f:
            raw = tomllib.load(f)
    except FileNotFoundError as e:
        raise ConfigError(f"Config file not found: {path}") from e
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"{path} is not valid TOML: {e}") from e

    try:
        team = get_team(raw.get("team", {}).get("abbrev", ""))
    except ValueError as e:
        raise ConfigError(f"[team] abbrev: {e}") from e

    t = raw.get("time", {})
    local_tz = _zone(t.get("local_timezone") or team.timezone, "local_timezone")
    display_name = t.get("display_timezone") or t.get("local_timezone") or team.timezone
    display_tz = _zone(display_name, "display_timezone")

    llm = raw.get("llm", {})
    provider = (llm.get("provider") or "anthropic").strip().lower()
    if provider not in PROVIDERS:
        raise ConfigError(f"[llm] provider = {provider!r}; use one of {', '.join(PROVIDERS)}")
    model = (llm.get("model") or DEFAULT_MODELS[provider]).strip()
    base_url = (llm.get("base_url") or "").strip()
    if provider == "openai_compatible" and not (model and base_url):
        raise ConfigError("[llm] openai_compatible needs both model and base_url")

    email = raw.get("email", {})
    hide = {c.strip().lower() for c in email.get("hide_cards", [])}
    unknown = hide - set(CARD_KEYS)
    if unknown:
        raise ConfigError(
            f"[email] hide_cards: unknown {sorted(unknown)}; use any of {', '.join(CARD_KEYS)}"
        )

    return Settings(
        team=team,
        local_tz=local_tz,
        display_tz=display_tz,
        llm=LLMSettings(provider, model, base_url, API_KEY_ENV[provider]),
        newsletter_name=(email.get("newsletter_name") or f"{team.nickname} Daily").strip(),
        from_address=(email.get("from_address") or "onboarding@resend.dev").strip(),
        hide_cards=frozenset(hide),
        people=tuple(p.strip() for p in raw.get("on_this_day", {}).get("people", []) if p.strip()),
    )


SETTINGS = load_settings()
TEAM = SETTINGS.team
