"""HTML email builder and Resend sender for the digest and season recap.

Modules:
    theme            colours, fonts, formatting helpers, section marker, logo URLs
    cards_game       last game score card, goal log, three stars
    cards_form       series and form, Suffer-O-Meter, Season 5v5
    cards_next       Next Up and Coming Up
    cards_standings  Western standings, playoff race, magic number
    cards_playoffs   playoff bracket and series view
    cards_people     top scorers, player of the week, injuries, prospects
    cards_content    header, preheader, briefing, What We Learned, On This Day,
                     fine print
    digest_html      build_html, _finalize_html, render_email
    plaintext        build_plain_text
    recap            season recap HTML
    send             send_email, send_recap_email (Resend)

The names below are re-exported so `from emailer import ...` keeps working.
"""

from emailer.cards_content import PREHEADER_MAX, _get_preheader
from emailer.cards_form import five_v_five_reading
from emailer.digest_html import _finalize_html, build_html, render_email
from emailer.plaintext import build_plain_text
from emailer.recap import build_recap_html
from emailer.send import send_email, send_recap_email

__all__ = [
    "PREHEADER_MAX",
    "_finalize_html",
    "_get_preheader",
    "build_html",
    "build_plain_text",
    "build_recap_html",
    "five_v_five_reading",
    "render_email",
    "send_email",
    "send_recap_email",
]
