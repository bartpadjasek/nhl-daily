"""Provider adapters in llm.py, with fake SDK modules (no network)."""

import sys
from types import ModuleType, SimpleNamespace

import pytest

import llm


def _settings(provider, model, base_url=""):
    return SimpleNamespace(
        provider=provider, model=model, base_url=base_url, api_key_env="TEST_KEY"
    )


@pytest.fixture
def key(monkeypatch):
    monkeypatch.setenv("TEST_KEY", "k")


def test_anthropic_current_model_gets_headroom_effort_fallbacks_and_text_only(monkeypatch, key):
    calls = []

    class Messages:
        def create(self, **kw):
            calls.append(kw)
            blocks = [
                SimpleNamespace(type="thinking", thinking=""),
                SimpleNamespace(type="text", text="Hello."),
            ]
            return SimpleNamespace(content=blocks, stop_reason="end_turn")

    fake = ModuleType("anthropic")
    fake.Anthropic = lambda api_key: SimpleNamespace(
        messages=Messages(), beta=SimpleNamespace(messages=Messages())
    )
    monkeypatch.setitem(sys.modules, "anthropic", fake)
    monkeypatch.setattr(llm, "LLM", _settings("anthropic", "claude-opus-5-5"))

    out = llm.complete("sys", "user", 30)
    assert out.text == "Hello."
    kw = calls[0]
    assert kw["max_tokens"] == 30 + llm.THINKING_HEADROOM
    assert kw["output_config"] == {"effort": "low"}
    assert kw["fallbacks"] == "default" and "tools" not in kw

    llm.complete("sys", "user", 1000, web_search=True)
    assert calls[1]["tools"][0]["type"] == "web_search_20260209"


def test_anthropic_pause_turn_is_resumed_and_refusal_raises(monkeypatch, key):
    replies = [
        SimpleNamespace(
            content=[SimpleNamespace(type="text", text="part")], stop_reason="pause_turn"
        ),
        SimpleNamespace(
            content=[SimpleNamespace(type="text", text="done")], stop_reason="end_turn"
        ),
        SimpleNamespace(content=[], stop_reason="refusal"),
    ]
    fake = ModuleType("anthropic")
    msgs = SimpleNamespace(create=lambda **kw: replies.pop(0))
    fake.Anthropic = lambda api_key: SimpleNamespace(
        messages=msgs, beta=SimpleNamespace(messages=msgs)
    )
    monkeypatch.setitem(sys.modules, "anthropic", fake)
    monkeypatch.setattr(llm, "LLM", _settings("anthropic", "claude-haiku-4-5"))
    assert llm.complete("s", "u", 100, web_search=True).text == "done"
    with pytest.raises(llm.LLMError):
        llm.complete("s", "u", 100)


@pytest.mark.parametrize(
    "provider, token_arg",
    [("openai", "max_completion_tokens"), ("openai_compatible", "max_tokens")],
)
def test_openai_and_compatible(monkeypatch, key, provider, token_arg):
    seen = {}

    def create(**kw):
        seen.update(kw)
        msg = SimpleNamespace(content=" Hi ", refusal=None)
        return SimpleNamespace(choices=[SimpleNamespace(message=msg, finish_reason="length")])

    fake = ModuleType("openai")

    def client(api_key, base_url):
        seen["base_url"] = base_url
        return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))

    fake.OpenAI = client
    monkeypatch.setitem(sys.modules, "openai", fake)
    base = "http://localhost:11434/v1" if provider == "openai_compatible" else ""
    monkeypatch.setattr(llm, "LLM", _settings(provider, "m", base))
    out = llm.complete("sys", "user", 50)
    assert (out.text, out.stop_reason) == ("Hi", "max_tokens")
    assert seen[token_arg] == 50 and seen["messages"][0] == {"role": "system", "content": "sys"}
    assert seen["base_url"] == (base or None)


def test_gemini_flash_turns_thinking_off(monkeypatch, key):
    seen = {}
    google = ModuleType("google")
    genai = ModuleType("google.genai")
    types = ModuleType("google.genai.types")
    types.ThinkingConfig = lambda **kw: ("thinking", kw)
    types.GenerateContentConfig = lambda **kw: kw

    def generate_content(model, contents, config):
        seen.update(config)
        return SimpleNamespace(text="Ok", candidates=[SimpleNamespace(finish_reason="STOP")])

    genai.Client = lambda api_key: SimpleNamespace(
        models=SimpleNamespace(generate_content=generate_content)
    )
    genai.types = types
    google.genai = genai
    for name, mod in [("google", google), ("google.genai", genai), ("google.genai.types", types)]:
        monkeypatch.setitem(sys.modules, name, mod)
    monkeypatch.setattr(llm, "LLM", _settings("gemini", "gemini-2.5-flash"))
    assert llm.complete("sys", "user", 40).text == "Ok"
    assert seen["thinking_config"] == ("thinking", {"thinking_budget": 0})
    assert seen["max_output_tokens"] == 40 and seen["system_instruction"] == "sys"


def test_retryable_errors_are_retried(monkeypatch, key):
    attempts = []

    class Busy(Exception):
        status_code = 529

    def flaky(*a):
        attempts.append(1)
        if len(attempts) < 3:
            raise Busy("overloaded")
        return llm.Completion("ok", "end_turn")

    monkeypatch.setattr(llm, "_openai", flaky)
    monkeypatch.setattr(llm, "LLM", _settings("openai", "m"))
    monkeypatch.setattr(llm.time, "sleep", lambda s: None)
    assert llm.complete("s", "u", 10).text == "ok" and len(attempts) == 3
