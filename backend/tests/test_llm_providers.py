"""Tests for the pluggable LLM provider layer (#2443).

No network: the SDK clients on each provider are replaced with fakes so we can
assert request translation, response normalization, and tool-message shaping.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.ai.providers import resolve_provider
from app.ai.providers.anthropic_provider import AnthropicLLMProvider
from app.ai.providers.base import flatten_system
from app.ai.providers.openai_compat_provider import (
    OpenAICompatLLMProvider,
    _to_openai_tool_choice,
    _to_openai_tools,
)
from app.ai.providers.pricing import calculate_cost_cents

_TOOL = {
    "name": "save",
    "description": "Save it",
    "input_schema": {"type": "object", "properties": {"x": {"type": "integer"}}},
}


# ── flatten_system / tool translation ─────────────────────────────


def test_flatten_system_strips_cache_control():
    blocks = [
        {"type": "text", "text": "A", "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": "B"},
    ]
    assert flatten_system(blocks) == "A\n\nB"
    assert flatten_system("plain") == "plain"


def test_to_openai_tools_and_choice():
    tools = _to_openai_tools([_TOOL])
    assert tools[0]["type"] == "function"
    assert tools[0]["function"]["name"] == "save"
    assert tools[0]["function"]["parameters"] == _TOOL["input_schema"]

    assert _to_openai_tool_choice({"type": "tool", "name": "save"}) == {
        "type": "function",
        "function": {"name": "save"},
    }
    assert _to_openai_tool_choice({"type": "any"}) == "required"
    assert _to_openai_tool_choice({"type": "auto"}) == "auto"


# ── Anthropic provider ────────────────────────────────────────────


class _FakeStreamCtx:
    def __init__(self, message):
        self._m = message

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get_final_message(self):
        return self._m


class _FakeAnthropic:
    def __init__(self, message):
        self.message = message
        self.messages = SimpleNamespace(stream=self._stream)

    def _stream(self, **kwargs):
        self.last_kwargs = kwargs
        return _FakeStreamCtx(self.message)


async def test_anthropic_complete_parses_tool_use_and_usage():
    message = SimpleNamespace(
        content=[
            SimpleNamespace(type="text", text="hello"),
            SimpleNamespace(type="tool_use", id="tu_1", name="save", input={"x": 1}),
        ],
        stop_reason="tool_use",
        usage=SimpleNamespace(
            input_tokens=10,
            output_tokens=5,
            cache_creation_input_tokens=0,
            cache_read_input_tokens=2,
        ),
    )
    provider = AnthropicLLMProvider(api_key="sk-test")
    provider._client = _FakeAnthropic(message)

    result = await provider.complete(
        system=[{"type": "text", "text": "sys", "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": "hi"}],
        max_tokens=100,
        temperature=0.3,
        model="claude-sonnet-4-6",
        tools=[_TOOL],
        tool_choice={"type": "tool", "name": "save"},
    )

    assert result.text == "hello"
    assert result.stop_reason == "tool_use"
    assert result.tool_calls[0].name == "save"
    assert result.tool_calls[0].input == {"x": 1}
    assert result.usage["input_tokens"] == 10
    assert result.usage["cache_read_input_tokens"] == 2
    # cache_control blocks pass through untouched on Anthropic.
    assert provider._client.last_kwargs["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert result.assistant_message == {"role": "assistant", "content": message.content}


async def test_anthropic_omits_temperature_for_models_that_reject_it():
    # claude-opus-4-8 (like opus-4-7 / sonnet-5 / fable-5) 400s on any sampling
    # param; claude-sonnet-4-6 still accepts temperature (#2575).
    message = SimpleNamespace(content=[], stop_reason="end_turn", usage=None)

    provider = AnthropicLLMProvider(api_key="sk-test")
    provider._client = _FakeAnthropic(message)
    await provider.complete(
        system="sys",
        messages=[{"role": "user", "content": "hi"}],
        max_tokens=100,
        temperature=0.3,
        model="claude-opus-4-8",
    )
    assert "temperature" not in provider._client.last_kwargs

    provider._client = _FakeAnthropic(message)
    await provider.complete(
        system="sys",
        messages=[{"role": "user", "content": "hi"}],
        max_tokens=100,
        temperature=0.3,
        model="claude-sonnet-4-6",
    )
    assert provider._client.last_kwargs["temperature"] == 0.3


async def test_anthropic_stream_omits_temperature_for_models_that_reject_it():
    # The tutor path goes through stream(); the same omission must apply there.
    class _EmptyStreamCtx(_FakeStreamCtx):
        def __aiter__(self):
            return self

        async def __anext__(self):
            raise StopAsyncIteration

    class _FakeAnthropicStream(_FakeAnthropic):
        def _stream(self, **kwargs):
            self.last_kwargs = kwargs
            return _EmptyStreamCtx(self.message)

    provider = AnthropicLLMProvider(api_key="sk-test")
    provider._client = _FakeAnthropicStream(None)
    async for _ in provider.stream(
        system="sys",
        user_message="hi",
        max_tokens=100,
        temperature=0.3,
        model="claude-opus-4-8",
    ):
        pass
    assert "temperature" not in provider._client.last_kwargs


def test_anthropic_tool_result_messages_shape():
    provider = AnthropicLLMProvider(api_key="sk-test")
    msgs = provider.build_tool_result_messages([{"tool_call_id": "tu_1", "content": "out"}])
    assert msgs == [
        {
            "role": "user",
            "content": [{"type": "tool_result", "tool_use_id": "tu_1", "content": "out"}],
        }
    ]
    assert provider.supports_cache_control is True


# ── OpenAI-compatible provider ────────────────────────────────────


class _FakeChatCompletions:
    def __init__(self, response):
        self._r = response

    async def create(self, **kwargs):
        self.kwargs = kwargs
        return self._r


class _FakeOpenAI:
    def __init__(self, response):
        self.chat = SimpleNamespace(completions=_FakeChatCompletions(response))


async def test_openai_compat_complete_parses_tool_calls_and_flattens_system():
    # Native forced-tool path: backend supports a forced tool_choice (default).
    response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content=None,
                    tool_calls=[
                        SimpleNamespace(
                            id="call_1",
                            function=SimpleNamespace(name="save", arguments='{"x": 1}'),
                        )
                    ],
                )
            )
        ],
        usage=SimpleNamespace(prompt_tokens=20, completion_tokens=8, prompt_tokens_details=None),
    )
    provider = OpenAICompatLLMProvider(api_key="sk-test")
    provider._client = _FakeOpenAI(response)

    result = await provider.complete(
        system=[{"type": "text", "text": "sys", "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": "hi"}],
        max_tokens=100,
        temperature=0.5,
        model="gpt-4o-mini",
        tools=[_TOOL],
        tool_choice={"type": "tool", "name": "save"},
    )

    assert result.tool_calls[0].input == {"x": 1}
    assert result.stop_reason == "tool_use"
    assert result.usage["input_tokens"] == 20
    assert result.usage["output_tokens"] == 8
    assert result.usage["cache_creation_input_tokens"] == 0

    sent = provider._client.chat.completions.kwargs
    # system flattened to a leading system message, cache_control stripped.
    assert sent["messages"][0] == {"role": "system", "content": "sys"}
    assert sent["tools"][0]["type"] == "function"
    assert sent["tool_choice"] == {"type": "function", "function": {"name": "save"}}
    # arbitrary temperature forwarded on a non-reasoning chat model.
    assert sent["temperature"] == 0.5
    # assistant_message carries OpenAI-shaped tool_calls for the next turn.
    assert result.assistant_message["tool_calls"][0]["function"]["name"] == "save"


async def test_openai_compat_emulates_forced_tool_via_json_mode():
    # Moonshot rejects forced tool_choice → emulate via JSON mode and surface a
    # synthetic ToolCall so call sites keep reading result.tool_calls[0].
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content='{"x": 7}', tool_calls=None))],
        usage=SimpleNamespace(prompt_tokens=12, completion_tokens=4, prompt_tokens_details=None),
    )
    provider = OpenAICompatLLMProvider(api_key="sk-test", supports_forced_tool_choice=False)
    provider._client = _FakeOpenAI(response)

    result = await provider.complete(
        system="sys",
        messages=[{"role": "user", "content": "hi"}],
        max_tokens=100,
        temperature=0.7,
        model="moonshot-v1-128k",
        tools=[_TOOL],
        tool_choice={"type": "tool", "name": "save"},
    )

    assert result.stop_reason == "tool_use"
    assert result.tool_calls[0].name == "save"
    assert result.tool_calls[0].input == {"x": 7}

    sent = provider._client.chat.completions.kwargs
    # No tools/tool_choice sent; JSON mode requested instead.
    assert "tools" not in sent and "tool_choice" not in sent
    assert sent["response_format"] == {"type": "json_object"}
    # The tool's input_schema is injected into the system prompt.
    assert "save" in sent["messages"][0]["content"]
    assert "input_schema" not in sent["messages"][0]["content"]  # schema body, not the key
    # Synthetic assistant tool_call for any follow-up turn.
    assert result.assistant_message["tool_calls"][0]["function"]["name"] == "save"


async def test_openai_compat_emulated_tool_bad_json_returns_no_tool_call():
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="not json", tool_calls=None))],
        usage=SimpleNamespace(prompt_tokens=5, completion_tokens=2, prompt_tokens_details=None),
    )
    provider = OpenAICompatLLMProvider(api_key="sk-test", supports_forced_tool_choice=False)
    provider._client = _FakeOpenAI(response)

    result = await provider.complete(
        system="sys",
        messages=[{"role": "user", "content": "hi"}],
        max_tokens=50,
        temperature=0.7,
        model="moonshot-v1-128k",
        tools=[_TOOL],
        tool_choice={"type": "tool", "name": "save"},
    )
    assert result.tool_calls == []
    assert result.stop_reason == "end_turn"
    assert result.text == "not json"


async def test_openai_compat_json_object_without_tools():
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content='{"ok": true}', tool_calls=None))],
        usage=SimpleNamespace(prompt_tokens=5, completion_tokens=3, prompt_tokens_details=None),
    )
    provider = OpenAICompatLLMProvider(api_key="sk-test")
    provider._client = _FakeOpenAI(response)

    result = await provider.complete(
        system="sys",
        messages=[{"role": "user", "content": "hi"}],
        max_tokens=50,
        temperature=0.0,
        model="moonshot-v1-128k",
        json_object=True,
    )
    assert result.text == '{"ok": true}'
    assert result.stop_reason == "end_turn"
    assert provider._client.chat.completions.kwargs["response_format"] == {"type": "json_object"}


async def test_openai_compat_kimi_k26_disables_thinking_and_pins_temperature():
    # kimi-k2.6 is a reasoning model: thinking on by default and temperature is
    # fixed by the model. The provider must disable thinking and pin temperature
    # to the non-thinking value (0.6), regardless of the requested temperature.
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content='{"ok": true}', tool_calls=None))],
        usage=SimpleNamespace(prompt_tokens=5, completion_tokens=3, prompt_tokens_details=None),
    )
    provider = OpenAICompatLLMProvider(api_key="sk-test", supports_forced_tool_choice=False)
    provider._client = _FakeOpenAI(response)

    await provider.complete(
        system="sys",
        messages=[{"role": "user", "content": "hi"}],
        max_tokens=50,
        temperature=0.7,  # requested value must be overridden
        model="kimi-k2.6",
        json_object=True,
    )

    sent = provider._client.chat.completions.kwargs
    assert sent["temperature"] == 0.6
    assert sent["extra_body"] == {"thinking": {"type": "disabled"}}


async def test_openai_compat_moonshot_v1_keeps_temperature_and_no_thinking():
    # Regression guard: the standard chat family (moonshot-v1-*) is unaffected —
    # arbitrary temperature forwarded, no thinking/extra_body injected.
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content='{"ok": true}', tool_calls=None))],
        usage=SimpleNamespace(prompt_tokens=5, completion_tokens=3, prompt_tokens_details=None),
    )
    provider = OpenAICompatLLMProvider(api_key="sk-test")
    provider._client = _FakeOpenAI(response)

    await provider.complete(
        system="sys",
        messages=[{"role": "user", "content": "hi"}],
        max_tokens=50,
        temperature=0.7,
        model="moonshot-v1-128k",
        json_object=True,
    )

    sent = provider._client.chat.completions.kwargs
    assert sent["temperature"] == 0.7
    assert "extra_body" not in sent


async def test_openai_compat_stream_kimi_k26_overrides_apply():
    # The tutor streams through stream(); the same override must apply there or
    # kimi-k2.6 rejects the requested temperature.
    class _EmptyStream:
        def __aiter__(self):
            return self

        async def __anext__(self):
            raise StopAsyncIteration

    class _CapturingCompletions:
        async def create(self, **kwargs):
            self.kwargs = kwargs
            return _EmptyStream()

    provider = OpenAICompatLLMProvider(api_key="sk-test")
    completions = _CapturingCompletions()
    provider._client = SimpleNamespace(chat=SimpleNamespace(completions=completions))

    chunks = [
        c
        async for c in provider.stream(
            system="sys",
            user_message="hi",
            max_tokens=50,
            temperature=0.7,
            model="kimi-k2.6",
        )
    ]
    assert chunks == []
    assert completions.kwargs["temperature"] == 0.6
    assert completions.kwargs["extra_body"] == {"thinking": {"type": "disabled"}}
    assert completions.kwargs["stream"] is True


def test_openai_tool_result_messages_shape():
    provider = OpenAICompatLLMProvider(api_key="sk-test")
    msgs = provider.build_tool_result_messages([{"tool_call_id": "call_1", "content": "out"}])
    assert msgs == [{"role": "tool", "tool_call_id": "call_1", "content": "out"}]
    assert provider.supports_cache_control is False


# ── registry resolution ───────────────────────────────────────────


@pytest.fixture
def _fake_settings(monkeypatch):
    settings = SimpleNamespace(
        anthropic_api_key="sk-anthropic",
        moonshot_api_key="sk-moonshot",
        moonshot_base_url="https://api.moonshot.ai/v1",
        openai_api_key="sk-openai",
        openrouter_api_key="sk-openrouter",
        openrouter_base_url="https://openrouter.ai/api/v1",
    )
    monkeypatch.setattr("app.ai.providers.registry.get_settings", lambda: settings)
    return settings


def test_resolve_provider_by_prefix(_fake_settings):
    assert isinstance(resolve_provider("claude-sonnet-4-6"), AnthropicLLMProvider)
    assert isinstance(resolve_provider("moonshot-v1-128k"), OpenAICompatLLMProvider)
    assert isinstance(resolve_provider("gpt-4o-mini"), OpenAICompatLLMProvider)
    assert isinstance(resolve_provider("moonshotai/kimi-k2.6"), OpenAICompatLLMProvider)


def test_resolve_provider_moonshot_disables_forced_tool_choice(_fake_settings):
    # Moonshot can't force a single tool — the provider must emulate it.
    moonshot = resolve_provider("moonshot-v1-128k")
    assert moonshot._supports_forced_tool_choice is False
    # kimi-k2.6 routes to Moonshot and likewise emulates forced tool_choice.
    assert resolve_provider("kimi-k2.6")._supports_forced_tool_choice is False
    # Other OpenAI-compatible backends keep native forced tool_choice.
    assert resolve_provider("gpt-4o-mini")._supports_forced_tool_choice is True


def test_resolve_provider_missing_key_raises(_fake_settings, monkeypatch):
    monkeypatch.setattr(_fake_settings, "moonshot_api_key", "")
    with pytest.raises(ValueError, match="MOONSHOT_API_KEY"):
        resolve_provider("moonshot-v1-128k")


def test_resolve_provider_unknown_model_raises(_fake_settings):
    with pytest.raises(ValueError, match="No provider mapping"):
        resolve_provider("llama-3")


# ── pricing ───────────────────────────────────────────────────────


def test_pricing_per_model():
    usage = {"input_tokens": 1_000_000, "output_tokens": 1_000_000}
    # Sonnet: $3 in + $15 out = 1800 cents.
    assert calculate_cost_cents("claude-sonnet-4-6", usage) == 1800
    # moonshot-v1-128k: $2.00 in + $5.00 out = 700 cents.
    assert calculate_cost_cents("moonshot-v1-128k", usage) == 700
    # kimi-k2.6 has its own row (placeholder rates), not the default fallback.
    assert calculate_cost_cents("kimi-k2.6", usage) == 700
    # Unknown model falls back to the default (Sonnet) table.
    assert calculate_cost_cents("mystery", usage) == 1800
