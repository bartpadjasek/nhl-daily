# CLAUDE.md

Guidance for Claude Code (claude.ai/code) when working in this repository.

## What this project is

NHL Daily: a morning email about one NHL team (chosen in `config.toml`) the day after every game. Python, run by GitHub Actions; content written by an AI model from any supported provider (`llm.py`); sent with Resend.

## Commands

```bash
pip install -r requirements-dev.txt
python main.py --preview     # build the email into preview/ — never sends, never writes game_log.json
pytest                       # saved fixtures, no network (conftest blocks it)
ruff check . && ruff format .
NHL_DAILY_CONFIG=other.toml python main.py --preview   # try another team or provider
```

Never use `--now`, `--force` or `--force-recap` to test: they send email and append to `game_log.json`.

## Configuration

- `config.toml` → `config.py` (`SETTINGS`, `TEAM`), loaded at import. Every module reads the team, time zones, provider and card switches from there; nothing team-specific is hard-coded. `team.py` has the static 32-team table.
- Tests pin `NHL_DAILY_CONFIG=tests/config_test.toml` (Edmonton, Stockholm display time) because the fixtures are Edmonton games. Keep it that way so a user's `config.toml` never changes test results.
- Secrets are environment variables: `RESEND_API_KEY`, `TO_EMAIL`, the provider key (`config.API_KEY_ENV`), optional `OPENWEATHERMAP_API_KEY`.

## Key behaviour

- **Send gate:** `scheduler._has_unsent_game()` sends only if `nhl.latest_completed_game()` (gameState OFF, last 2 days, local time) isn't in `game_log.json`. `--force` bypasses it.
- **Model calls:** all go through `llm.complete()` (`digest._call_api` adapts the generators to it; `season_recap` calls it directly). Only Anthropic gets web search (season recap). Provider SDKs are imported lazily. Preview mode records every prompt and stubs the model when the provider key is missing.
- **Facts are computed in code.** Prompts get a KEY FACTS block (`digest._key_facts_lines`): last game and previous meeting, season series in words, shutout, game-winning goal with timing words, next game and last meeting, road trip / homestand position, back-to-backs, division gap, goalie starts (`game_log.goalie_starts`), point streaks of 5+. Prompt team words come from `NAME`/`NICK`/`PLACE`/`ABBR`/`DIV`/`CONF` (digest.py, emailer/theme.py).
- **One reference date per run:** `nhl.reference_date()` = later of today in `LOCAL_TZ` and the day after the reported game; stored as `data["reference_date"]`.
- **One clock:** content time uses `nhl.local_now()` or the reference date; `tests/test_clock.py` fails on a new direct clock call.
- **Conference logic is generic:** `nhl.our_conference()` reads our conference and divisions from live standings (team table as fallback). Standings, magic number and playoff race use it.
- **NHL requests** go through `nhl._get`: one session, ≥0.25 s apart, retries 429/5xx, cached per run.
- **Missing-data report:** code that drops a section calls `run_report.record(section, reason)`; listed in the footer and `preview/report.json`.
- **Escaping:** every outside string goes into HTML through `emailer.theme.esc()`.
- **Golden emails:** `tests/test_golden.py` compares rendered output byte for byte with `tests/golden/`. Regenerate only for intended look changes: `UPDATE_GOLDEN=1 pytest tests/test_golden.py`.
- **Hidden cards:** `config.toml [email] hide_cards`; `digest_html.build_html` blanks them and the scheduler skips their model calls.

## emailer/ package

`theme` (constants, team names, `esc`, helpers) · `cards_game` · `cards_form` · `cards_next` · `cards_standings` · `cards_playoffs` · `cards_people` · `cards_content` · `digest_html` (card order, `_finalize_html`, `render_email`) · `plaintext` · `recap` · `send`. Cards import only from `theme`; only `__init__` imports `send`.

## Workflows

| Workflow | Trigger | Does |
|---|---|---|
| `digest.yml` | cron 04:00 + 14:00 UTC | `main.py --now`; commits `game_log.json` (3 push attempts) |
| `digest-force.yml` | manual | `main.py --force` |
| `recap-force.yml` | manual | `main.py --force-recap` |
| `lint.yml` | push to main, PRs | ruff + pytest |
