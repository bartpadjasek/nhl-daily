"""Sending through the Resend API."""

import logging
import os

import resend
from dotenv import load_dotenv

from config import SETTINGS
from emailer.digest_html import render_email
from emailer.recap import build_recap_html
from emailer.theme import NEWSLETTER

load_dotenv()

logger = logging.getLogger(__name__)


FROM_ADDRESS = f"{NEWSLETTER} <{SETTINGS.from_address}>"  # config.toml [email]


def send_recap_email(subject: str, recap_data: dict) -> None:
    """Send the season recap email via the Resend API.

    Args:
        subject: Email subject line.
        recap_data: Structured recap data dict from season_recap.py.

    Raises:
        EnvironmentError: If required credentials are missing from .env.
    """
    api_key = os.environ.get("RESEND_API_KEY")
    to_email = os.environ.get("TO_EMAIL")

    if not api_key or not to_email:
        raise OSError(
            "Missing credentials. Ensure RESEND_API_KEY and TO_EMAIL are set in your .env file."
        )

    resend.api_key = api_key

    html_body = build_recap_html(recap_data)

    last_game = recap_data.get("last_game") or {}
    lg_date = last_game.get("date", "")
    season_label = ""
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

    plain_lines = [
        f"{NEWSLETTER.upper()} — {season_label or 'SEASON'} RECAP",
        "=" * 50,
        "",
        recap_data.get("overview", ""),
        "",
        "THE GOOD",
        "-" * 20,
        (recap_data.get("good_bad_middling") or {}).get("good", ""),
        "",
        "THE BAD",
        "-" * 20,
        (recap_data.get("good_bad_middling") or {}).get("bad", ""),
        "",
        "THE MIDDLING",
        "-" * 20,
        (recap_data.get("good_bad_middling") or {}).get("middling", ""),
        "",
        "PLAYER GRADES",
        "-" * 20,
    ]
    for pg in recap_data.get("player_grades") or []:
        plain_lines.append(
            f"{pg.get('name', '')} ({pg.get('position', '')}) — {pg.get('grade', '?')}: {pg.get('reasoning', '')}"
        )
    plain_lines += [
        "",
        "OFFSEASON PRIORITIES",
        "-" * 20,
    ]
    for i, p in enumerate(recap_data.get("offseason_priorities") or [], 1):
        plain_lines.append(
            f"{i}. [{p.get('label', 'Monitor')}] {p.get('priority', '')}: {p.get('detail', '')}"
        )
    plain_lines += ["", "=" * 50, f"{NEWSLETTER} — powered by NHL API & AI"]
    plain_body = "\n".join(plain_lines)

    logger.info("Sending season recap email via Resend to %s", to_email)

    params: resend.Emails.SendParams = {
        "from": FROM_ADDRESS,
        "to": [to_email],
        "subject": subject,
        "html": html_body,
        "text": plain_body,
    }

    response = resend.Emails.send(params)
    logger.info("Recap email sent via Resend, id=%s", response.get("id"))


def send_email(subject: str, briefing: str, data: dict) -> None:
    """Send the digest via the Resend API.

    Loads credentials from environment variables in .env:
    - RESEND_API_KEY: API key from resend.com
    - TO_EMAIL: recipient email address

    Args:
        subject: Email subject line.
        briefing: Plain-text briefing from digest.generate_digest().
        data: Structured data dict from nhl.get_team_data().

    Raises:
        EnvironmentError: If required credentials are missing from .env.
    """
    api_key = os.environ.get("RESEND_API_KEY")
    to_email = os.environ.get("TO_EMAIL")

    if not api_key or not to_email:
        raise OSError(
            "Missing credentials. Ensure RESEND_API_KEY and TO_EMAIL are set in your .env file."
        )

    resend.api_key = api_key

    html_body, plain_body = render_email(subject, briefing, data)

    logger.info("Sending email via Resend to %s", to_email)

    params: resend.Emails.SendParams = {
        "from": FROM_ADDRESS,
        "to": [to_email],
        "subject": subject,
        "html": html_body,
        "text": plain_body,
    }

    response = resend.Emails.send(params)
    logger.info("Email sent via Resend, id=%s", response.get("id"))
