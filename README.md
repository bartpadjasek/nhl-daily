# NHL Daily

A morning email about your NHL team, the day after every game. It pulls the result, standings and schedule from the NHL's public data, has an AI model write a short briefing, and sends a mobile-friendly email to your inbox.

- **Any team.** Pick yours in one line of `config.toml`.
- **Any AI provider.** Anthropic (Claude), OpenAI, Google Gemini, or any OpenAI-compatible API (OpenRouter, Groq, Ollama, LM Studio).
- **No server.** It runs on GitHub Actions, free for public repositories.

> Not affiliated with or endorsed by the NHL. It uses the NHL's public (undocumented) web API, which can change without notice. Team logos are NHL trademarks, loaded from the NHL's own image server.

---

## What's in the email

| Card | What it shows |
|---|---|
| **Last Game** | Final score (OT/SO and shutouts marked), date and arena, team stats, both goalies |
| **Today's Briefing** | 200–250 words from the AI model, built on facts computed in code (dates, venues, streaks, road trips) |
| **Next Up** | Opponent, start time in your time zone, back-to-backs and road-trip position, their record and players to watch, weather at the arena |
| **Suffer-O-Meter** | A 1–10 "how much did that hurt" score, with the reasons |
| **Goal Log** | Every goal by period, with assists and strength |
| **Three Stars** | The game's three stars (goalies: saves and shots) |
| **Series · Form** | Season series against the last opponent, last 10 results |
| **Season 5v5** | Shot attempts (CF%), unblocked attempts (FF%) and PDO, with a one-line reading |
| **What We Learned** | Three short AI takeaways that add to the briefing |
| **On This Day** | A team event from Wikipedia for today's date, when there is one |
| **Injury Report** | Who's out, with injury type and expected return when ESPN has them |
| **Standings** | Your conference in playoff format: division top 3s, wild cards, playoff line |
| **Playoff Race** | From game 62: your division rivals and the wild-card race, with an AI read |
| **Team Leaders** | Your top scorers |
| **Player of the Week · Milestones** | Best player over the last 5 games, and milestones coming up |
| **Prospects** | Your prospects' stats in every league |
| **Coming Up** | The next five games |

In the playoffs, the standings become the bracket and your series. A week after the season ends, one **season recap** email replaces the digest: an overview, the good / bad / middling, player grades and offseason priorities.

Any card can be switched off in `config.toml`. If a data source fails on the day, the card is left out and the footer says so.

---

## Set it up (about 15 minutes)

You need a GitHub account, a free [Resend](https://resend.com) account for sending email, and an API key from one AI provider.

### 1. Copy this repository

Click **Use this template → Create a new repository** (or **Fork**). Make your copy **public** if you want GitHub Actions minutes for free; a private repo also works, using your account's included minutes.

### 2. Choose your team

Open `config.toml` in your copy (click it on GitHub, then the pencil icon) and set your team:

```toml
[team]
abbrev = "TOR"
```

The abbreviations are listed in the file. Commit the change.

While you're there, you can also set:

- **`[time]`**: which time zone start times are shown in. By default it's your team's home time zone.
- **`[llm]`**: which AI provider and model to use (see [AI providers](#ai-providers)).
- **`[email]`**: the newsletter's name, and `hide_cards` to leave out cards you don't want.
- **`[on_this_day]`**: franchise legends whose names count as "team history" on Wikipedia.

### 3. Get your API keys

**Resend** (email delivery):

1. Sign up at [resend.com](https://resend.com) and create an API key.
2. On the free setup, Resend only delivers to **the email address you signed up with**, from `onboarding@resend.dev`. To send to anyone else, [verify a domain](https://resend.com/domains) in Resend and set `from_address` in `config.toml` to an address on it.

**Your AI provider**: create a key with whichever provider you set in `config.toml` (see the table below).

**Weather** (optional): a free key from [OpenWeatherMap](https://openweathermap.org/api) adds the arena city's weather to Next Up.

### 4. Add the keys as GitHub secrets

In your repository: **Settings → Secrets and variables → Actions → New repository secret**. Add:

| Secret | Value |
|---|---|
| `RESEND_API_KEY` | Your Resend API key |
| `TO_EMAIL` | Where to send the email |
| One of `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY`, `LLM_API_KEY` | The key for the provider in `config.toml` |
| `OPENWEATHERMAP_API_KEY` | Optional |

### 5. Turn on the workflows

Open the **Actions** tab. On a fork, GitHub asks you to enable workflows first: click the button.

### 6. Send a test email

**Actions → NHL Daily Digest (Force) → Run workflow.** In a minute or two you should have an email about your team's last game.

After that it runs by itself: twice a day it checks for a finished game that hasn't been emailed yet, sends it once, and skips the rest of the time.

---

## AI providers

Set `provider` (and optionally `model`) under `[llm]` in `config.toml`, and add the matching secret.

| `provider` | Secret | Default `model` | Notes |
|---|---|---|---|
| `anthropic` | `ANTHROPIC_API_KEY` | `claude-opus-5-5` | Also gets web search for the season recap. |
| `openai` | `OPENAI_API_KEY` | `gpt-4.1` | Use a chat model. Reasoning models spend part of the small token budgets on thinking, so their answers can come back short. |
| `gemini` | `GEMINI_API_KEY` | `gemini-2.5-flash` | Free tier available from [Google AI Studio](https://aistudio.google.com/apikey). |
| `openai_compatible` | `LLM_API_KEY` (if needed) | none: set `model` | Any OpenAI-style API. Set `base_url`, e.g. `https://openrouter.ai/api/v1`, `https://api.groq.com/openai/v1`, or `http://localhost:11434/v1` for Ollama. |

Example, OpenRouter:

```toml
[llm]
provider = "openai_compatible"
model = "meta-llama/llama-3.3-70b-instruct"
base_url = "https://openrouter.ai/api/v1"
```

Each email makes about six short model calls. Only Anthropic runs web search for the season recap; with other providers the recap is written from the season's data alone. A local model (Ollama, LM Studio) only works on your own machine, not on GitHub Actions.

---

## Running it yourself

```bash
pip install -r requirements.txt
cp .env.example .env        # fill in the keys you use
```

```bash
python main.py --preview    # build the email into preview/ without sending it
python main.py --force      # send it now, for the most recent game
python main.py --now        # send only if there's a finished game not yet emailed
python main.py --force-recap   # send the season recap now
python main.py              # stay running and check daily (see scheduler.RUN_TIME)
```

`--preview` is the safe way to try things. It never sends email and never touches `game_log.json`. It writes `preview/digest.html` (open it in a browser), the plain-text version, the subject line, a report of any data that failed, and the exact prompts sent to the model. Without an API key it fills the AI parts with marked placeholder text.

To try another team without editing your config, point `NHL_DAILY_CONFIG` at a different file:

```bash
NHL_DAILY_CONFIG=my-other-team.toml python main.py --preview
```

---

## How it works

```
GitHub Actions (twice a day)
  → main.py --now
    → scheduler.run_pipeline()
        ├── nhl.py        game, standings, schedule, prospects   (NHL web API)
        ├── moneypuck.py  season 5v5 stats                       (NHL stats API)
        ├── news.py       headlines, as background for the model (Google News RSS)
        ├── weather.py    arena weather                          (OpenWeatherMap)
        ├── digest.py     briefing, takeaways, subject, fine print (llm.py → your provider)
        └── emailer/      HTML + plain-text email, sent with Resend
```

After each send, the workflow commits `game_log.json` back to your repository. That log is how it knows a game was already emailed, and it gives the model a memory of recent games.

Facts that are easy to get wrong (what day it was, where the game was played, how far into a road trip, goalie starts, point streaks) are computed in code and handed to the model as fixed "KEY FACTS". The model writes; it doesn't count.

| File | What's in it |
|---|---|
| `config.toml` | Your settings |
| `config.py` | Loads and checks `config.toml` |
| `team.py` | All 32 teams: names, home time zones, divisions |
| `llm.py` | One interface over the AI providers |
| `nhl.py` | NHL data and the facts computed from it |
| `digest.py` | Prompts and the AI-written parts |
| `emailer/` | One module per group of cards, plus page assembly and sending |
| `scheduler.py` | Runs everything in order; the Suffer-O-Meter |
| `season_recap.py` | The end-of-season email |
| `tests/` | Tests with saved NHL data and "golden" copies of the email |

## Developing

```bash
pip install -r requirements-dev.txt
pytest                               # no network needed
ruff check . && ruff format --check .
```

The golden tests render the email from saved data and compare it byte for byte with `tests/golden/`. If you change how the email looks on purpose, regenerate them with `UPDATE_GOLDEN=1 pytest tests/test_golden.py` and review the diff. The tests run as the Edmonton Oilers (`tests/config_test.toml`), whose games the saved data comes from; your own `config.toml` doesn't affect them.

## Troubleshooting

**No email after a Force run.** Open the run in the Actions tab and read the log. Look for:
- `Missing credentials`: `RESEND_API_KEY` or `TO_EMAIL` isn't set.
- `... is not set (needed for [llm] provider ...)`: the provider's key is missing.
- A Resend error: on Resend's test address, `TO_EMAIL` must be your Resend sign-up address.

**`Config file ... [team] abbrev`.** The abbreviation isn't one of the 32 listed in `config.toml`.

**A card is missing.** Check the footer line "Not included today: …", or `preview/report.json`. The NHL API sometimes rate-limits; the code retries, then leaves the card out rather than showing wrong data.

**Times look off by an hour.** Start times use `display_timezone`; "last night" and "tonight" use `local_timezone`. Both default to your team's home time zone.

**Scheduled runs don't happen.** GitHub can pause scheduled workflows in a public repository after 60 days without activity (for example over the off-season). Re-enable the workflow on the Actions tab. GitHub also often starts scheduled runs a few hours late; that's normal.

## License

MIT. See [LICENSE](LICENSE).
