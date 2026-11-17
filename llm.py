"""One small interface over the supported model providers.

    complete(system, user, max_tokens, web_search=False) -> Completion

Providers (config.toml [llm] provider):
    anthropic          Anthropic SDK; web search via the server-side web_search tool
    openai             OpenAI SDK (Chat Completions)
    gemini             Google Gen AI SDK
    openai_compatible  OpenAI SDK with base_url (OpenRouter, Groq, Ollama, LM Studio, ...)

Only Anthropic runs web search (used by the season recap); the others answer from
the data in the prompt. Each provider's SDK is imported only when it is used,
so a missing optional SDK only matters for the provider you picked.
"""

import logging
import os
import time
from dataclasses import dataclass

from config import SETTINGS

logger = logging.getLogger(__name__)

LLM = SETTINGS.llm
RETRY_DELAYS = (5, 15, 30)  # seconds, on overload / rate limit / server errors
RETRYABLE_STATUS = {408, 409, 429, 500, 502, 503, 504, 529}

# Claude models where thinking is on (and counts against max_tokens) and the
# effort setting exists. Older models get neither.
_CLAUDE_ADAPTIVE = (
    "claude-opus-5",
    "claude-sonnet-5",
    "claude-haiku-5",
    "claude-fable",
    "claude-mythos",
    "claude-opus-4-6",
    "claude-opus-4-7",
    "claude-opus-4-8",
    "claude-sonnet-4-6",
)
# Claude models that accept server-side refusal fallbacks
_CLAUDE_FALLBACKS = (
    "claude-fable-5-2",
    "claude-fable-5-1",
    "claude-opus-5-5",
    "claude-opus-5",
    "claude-sonnet-5-5",
)
THINKING_HEADROOM = 4000  # extra max_tokens so thinking never crowds out a short answer


@dataclass
class Completion:
    text: str
    stop_reason: str  # "end_turn", "max_tokens", "refusal" or the provider's own value


class LLMError(RuntimeError):
    """The provider failed or refused; callers fall back to their default text."""


def api_key() -> str:
    return os.environ.get(LLM.api_key_env, "")


def available() -> bool:
    """True if the configured provider can be called (a local server needs no key)."""
    return bool(api_key()) or LLM.provider == "openai_compatible"


def describe() -> str:
    return f"{LLM.provider}:{LLM.model}"


def complete(system: str, user: str, max_tokens: int, web_search: bool = False) -> Completion:
    """One system + user turn; returns the text answer. Retries transient errors."""
    call = {
        "anthropic": _anthropic,
        "openai": _openai,
        "openai_compatible": _openai,
        "gemini": _gemini,
    }[LLM.provider]
    if web_search and LLM.provider != "anthropic":
        logger.info(
            "Web search is only used with Anthropic; %s answers from the prompt", describe()
        )
    for attempt, delay in enumerate((*RETRY_DELAYS, None), start=1):
        try:
            return call(system, user, max_tokens, web_search)
        except LLMError:
            raise
        except Exception as e:
            status = getattr(e, "status_code", None) or getattr(e, "code", None)
            if delay is not None and status in RETRYABLE_STATUS:
                logger.warning(
                    "%s returned %s (attempt %d) — retrying in %ds",
                    describe(),
                    status,
                    attempt,
                    delay,
                )
                time.sleep(delay)
                continue
            raise LLMError(f"{describe()} call failed: {e}") from e
    raise LLMError(f"{describe()} kept failing")  # unreachable


# --- Anthropic ----------------------------------------------------------------


def _anthropic(system: str, user: str, max_tokens: int, web_search: bool) -> Completion:
    import anthropic

    client = anthropic.Anthropic(api_key=api_key())
    model = LLM.model
    adaptive = model.startswith(_CLAUDE_ADAPTIVE)
    kwargs: dict = {
        "model": model,
        "max_tokens": max_tokens + (THINKING_HEADROOM if adaptive else 0),
        "system": system,
        "messages": [{"role": "user", "content": user}],
    }
    if adaptive:
        # Short writing tasks: low effort keeps them quick and cheap; the recap
        # (with web research) gets more.
        kwargs["output_config"] = {"effort": "medium" if web_search else "low"}
    if web_search:
        kwargs["tools"] = [
            {
                "type": "web_search_20260209" if adaptive else "web_search_20250305",
                "name": "web_search",
            }
        ]
    use_fallbacks = model.startswith(_CLAUDE_FALLBACKS)
    if use_fallbacks:
        # On a safety decline, the API re-runs the request on a fallback model.
        kwargs["betas"] = ["server-side-fallback-2026-07-01"]
        kwargs["fallbacks"] = "default"
    create = client.beta.messages.create if use_fallbacks else client.messages.create

    response = create(**kwargs)
    # Web search runs on Anthropic's side; a long search pauses the turn — resend to continue.
    for _ in range(5):
        if response.stop_reason != "pause_turn":
            break
        kwargs["messages"] = [
            {"role": "user", "content": user},
            {"role": "assistant", "content": response.content},
        ]
        response = create(**kwargs)

    if response.stop_reason == "refusal":
        raise LLMError(f"{describe()} declined the request")
    text = "\n\n".join(b.text for b in response.content if getattr(b, "type", "") == "text")
    return Completion(text.strip(), response.stop_reason or "end_turn")


# --- OpenAI and OpenAI-compatible --------------------------------------------


def _openai(system: str, user: str, max_tokens: int, web_search: bool) -> Completion:
    import openai

    compatible = LLM.provider == "openai_compatible"
    client = openai.OpenAI(
        api_key=api_key() or "not-needed",  # local servers (Ollama, LM Studio) ignore the key
        base_url=LLM.base_url or None,
    )
    kwargs: dict = {
        "model": LLM.model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
    }
    # OpenAI's own API wants max_completion_tokens; many compatible servers only know max_tokens.
    kwargs["max_tokens" if compatible else "max_completion_tokens"] = max_tokens
    response = client.chat.completions.create(**kwargs)
    choice = response.choices[0]
    stop = {"stop": "end_turn", "length": "max_tokens", "content_filter": "refusal"}.get(
        choice.finish_reason or "stop", choice.finish_reason
    )
    if stop == "refusal" or getattr(choice.message, "refusal", None):
        raise LLMError(f"{describe()} declined the request")
    return Completion((choice.message.content or "").strip(), stop)


# --- Google Gemini -------------------------------------------------------------


def _gemini(system: str, user: str, max_tokens: int, web_search: bool) -> Completion:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key())
    model = LLM.model
    config: dict = {"system_instruction": system, "max_output_tokens": max_tokens}
    if "flash" in model:
        # Flash models can skip thinking entirely, so short answers aren't eaten by it.
        config["thinking_config"] = types.ThinkingConfig(thinking_budget=0)
    else:
        config["max_output_tokens"] = max_tokens + THINKING_HEADROOM  # thinking counts here
    response = client.models.generate_content(
        model=model, contents=user, config=types.GenerateContentConfig(**config)
    )
    candidate = (response.candidates or [None])[0]
    reason = str(getattr(candidate, "finish_reason", "") or "").upper()
    if "SAFETY" in reason or "PROHIBITED" in reason or "BLOCKLIST" in reason:
        raise LLMError(f"{describe()} declined the request")
    stop = "max_tokens" if "MAX_TOKENS" in reason else "end_turn"
    return Completion((response.text or "").strip(), stop)
