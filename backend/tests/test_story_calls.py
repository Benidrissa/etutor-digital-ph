"""Bounded story calls (#2702): max_tokens per kind, a cut answer, a call past its time.

Fake models only. The module pipeline under a slow or runaway model is
covered in ``test_story_module_service.py``.
"""

from __future__ import annotations

import asyncio
import copy
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.ai.claude_service import TruncatedResponse
from app.ai.providers.base import LLMResult
from app.domain.services import story_calls
from app.domain.services.story_calls import (
    CALL_CAPS,
    CALL_MARGIN_S,
    CONCISE_NOTICE,
    MAX_TOKENS,
    StoryCallTimeout,
    call_timeout,
    run_deadline,
    structured_call,
)
from app.domain.services.story_from_lesson_service import StoryFromLessonService
from tests.test_story_screenplay_module import pack
from tests.test_story_v4_builder import LANGUAGE, chapter_ctx, story_answer

# --------------------------------------------------------------------------
# The client: max_tokens per kind, a cut answer is a failure, with diagnostics
# --------------------------------------------------------------------------


def _claude(provider_result: LLMResult, ceiling: int = 64_000):
    """A real ClaudeService on a fake provider."""
    with patch("app.ai.claude_service.get_settings") as settings:
        settings.return_value = MagicMock(anthropic_api_key="k")
        with patch("app.ai.claude_service.SettingsCache") as cache:
            values = {"ai-max-tokens-content": ceiling, "ai-temperature-content": 0.7}
            cache.instance.return_value.get.side_effect = lambda key, default=None: values.get(
                key, default
            )
            from app.ai.claude_service import ClaudeService

            service = ClaudeService(model="claude-sonnet-4-6")
    provider = MagicMock()
    provider.complete = AsyncMock(return_value=provider_result)
    service._provider = lambda: provider
    return service, provider


RUNAWAY = '{"scenes": [' + '{"type": "say", "en": "and again"}, ' * 400


def test_the_64k_ceiling_is_the_content_models_and_a_story_call_has_its_own():
    service, provider = _claude(LLMResult(text='{"ok": true}', stop_reason="end_turn", usage={}))
    assert service._max_tokens == 64_000  # where the runaway's 64,000 came from
    bounded = service.with_max_tokens(MAX_TOKENS["story"])
    assert bounded._max_tokens == 12_000 and service._max_tokens == 64_000
    asyncio.run(bounded.generate_structured_content("s", "u", "story", max_retries=0))
    assert provider.complete.call_args.kwargs["max_tokens"] == 12_000
    # Never above the configured ceiling.
    small, _ = _claude(LLMResult(text="{}", stop_reason="end_turn", usage={}), ceiling=4_000)
    assert small.with_max_tokens(12_000)._max_tokens == 4_000


def test_a_story_answer_cut_at_max_tokens_is_a_failure_with_its_diagnostics():
    cut = LLMResult(text=RUNAWAY, stop_reason="max_tokens", usage={"output_tokens": 12_000})
    service, _ = _claude(cut)
    with pytest.raises(TruncatedResponse) as raised:
        asyncio.run(
            service.with_max_tokens(12_000).generate_structured_content(
                "s", "u", "story", max_retries=0
            )
        )
    error = raised.value
    assert isinstance(error, ValueError)  # callers that read it as unreadable still work
    assert error.output_tokens == 12_000 and error.length == len(RUNAWAY)
    assert error.head == RUNAWAY[:500] and error.tail == RUNAWAY[-500:]


def test_a_cut_but_parsable_answer_still_serves_other_callers():
    """Only the story calls (with_max_tokens) treat a cut answer as a failure."""
    cut = LLMResult(text='{"lesson": "ok"}', stop_reason="max_tokens", usage={})
    service, _ = _claude(cut)
    assert asyncio.run(service.generate_structured_content("s", "u", "lesson")) == {"lesson": "ok"}
    with pytest.raises(TruncatedResponse):
        asyncio.run(service.with_max_tokens(8_000).generate_structured_content("s", "u", "x"))


# --------------------------------------------------------------------------
# The timeout of a call: min(cap, deadline − margin)
# --------------------------------------------------------------------------


def test_each_kind_has_its_tokens_and_its_cap():
    assert MAX_TOKENS == {
        "bible": 6_000,
        "plan": 12_000,
        "pack": 8_000,
        "story": 12_000,
        "rally": 10_000,
        "judge": 2_000,
    }
    assert CALL_CAPS["story"] == 12_000 / 25 + 60 == 540
    assert max(CALL_CAPS.values()) < 1_068  # the runaway's 18 minutes


def test_the_timeout_is_the_cap_or_the_time_left_before_the_deadline():
    clock = {"now": 1000.0}
    assert call_timeout("story") == CALL_CAPS["story"]
    with run_deadline(2000.0, lambda: clock["now"]):
        assert call_timeout("story") == CALL_CAPS["story"]
        clock["now"] = 1900.0
        assert call_timeout("story") == 100.0 - CALL_MARGIN_S
        clock["now"] = 1990.0
        assert call_timeout("story") == 0.0
    assert call_timeout("story") == CALL_CAPS["story"]


class _Service:
    """A fake model with ``with_max_tokens``: records the limit of each call."""

    def __init__(self, answer: Any = None, delay: float = 0.0) -> None:
        self.answer = answer if answer is not None else {"ok": True}
        self.delay = delay
        self.limits: list[int] = []
        self.calls = 0

    def with_max_tokens(self, n: int):
        self.limits.append(n)
        return self

    async def generate_structured_content(self, system, user, content_type, max_retries=1):
        self.calls += 1
        await asyncio.sleep(self.delay)
        if isinstance(self.answer, BaseException):
            raise self.answer
        return copy.deepcopy(self.answer)


@pytest.mark.parametrize("kind", sorted(MAX_TOKENS))
def test_a_call_is_made_with_the_max_tokens_of_its_kind(kind):
    service = _Service()
    assert asyncio.run(structured_call(service, "s", "u", kind=kind)) == {"ok": True}
    assert service.limits == [MAX_TOKENS[kind]]


def test_a_call_past_its_time_is_a_story_call_timeout(monkeypatch):
    monkeypatch.setitem(CALL_CAPS, "story", 0.05)
    slow = _Service(delay=5.0)
    started = time.monotonic()
    with pytest.raises(StoryCallTimeout) as raised:
        asyncio.run(structured_call(slow, "s", "u", kind="story"))
    assert time.monotonic() - started < 2 and raised.value.kind == "story"
    # Past its cap with time left: a failure of the call, not the deadline.
    assert raised.value.reason == "cap" and not raised.value.at_deadline
    # No time left before the deadline: not even started — the deadline.
    with (
        run_deadline(time.monotonic() + 10, time.monotonic),
        pytest.raises(StoryCallTimeout) as late,
    ):
        asyncio.run(structured_call(slow, "s", "u", kind="story"))
    assert late.value.at_deadline
    assert slow.calls == 1


def test_a_call_bounded_by_the_deadline_says_so():
    from app.domain.services.story_calls import call_bound

    clock = {"now": 0.0}
    with run_deadline(10_000.0, lambda: clock["now"]):
        assert call_bound("story") == (CALL_CAPS["story"], "cap")
        clock["now"] = 10_000.0 - CALL_MARGIN_S - 100
        assert call_bound("story") == (100.0, "deadline")
    slow = _Service(delay=5.0)

    async def run() -> None:
        with run_deadline(time.monotonic() + CALL_MARGIN_S + 0.05, time.monotonic):
            await structured_call(slow, "s", "u", kind="story")

    with pytest.raises(StoryCallTimeout) as raised:
        asyncio.run(run())
    assert raised.value.at_deadline


def test_the_plans_max_tokens_grow_with_the_module():
    from app.domain.services.story_calls import plan_max_tokens

    assert [plan_max_tokens(n) for n in (1, 3, 6, 10, 14, 30)] == [
        8_000,
        8_500,
        13_000,
        19_000,
        24_000,
        24_000,
    ]


def test_the_plan_call_is_made_with_its_modules_max_tokens():
    from app.domain.services.story_calls import plan_max_tokens
    from app.domain.services.story_plan import StoryPlanService
    from tests.test_story_plan import answer, request

    req = request()
    service = _Service(answer={**answer(), "__complete": True})
    asyncio.run(
        StoryPlanService(service)._make(req, system_prompt="s", previous=None, rewritten=None)
    )
    assert service.limits == [plan_max_tokens(len(req.lessons))]


def test_the_providers_own_timeout_is_an_outage_not_a_deadline():
    with pytest.raises(TimeoutError) as raised:
        asyncio.run(structured_call(_Service(TimeoutError("read timeout")), "s", "u", kind="plan"))
    assert not isinstance(raised.value, StoryCallTimeout)


# --------------------------------------------------------------------------
# A runaway: never repaired at its budget, at most 2 calls
# --------------------------------------------------------------------------


class _Runaway:
    """Cut at max_tokens on every call (or only the first, with ``then``)."""

    def __init__(self, then: Any = None) -> None:
        self.then = then
        self.messages: list[str] = []

    async def generate_structured_content(self, system, user, content_type, max_retries=1):
        self.messages.append(user)
        if self.then is not None and len(self.messages) > 1:
            return copy.deepcopy(self.then)
        raise TruncatedResponse("story", output_tokens=12_000, length=40_000)


def test_a_runaway_chapter_costs_two_calls_and_is_never_repaired():
    model = _Runaway()
    service = StoryFromLessonService(model)
    ctx = chapter_ctx()
    generation = asyncio.run(
        service.generate_story(ctx, pack("1.1", LANGUAGE), system_prompt="s", max_repair_calls=3)
    )
    assert len(model.messages) == 2 and generation.model_calls == 2
    assert model.messages[1].startswith(CONCISE_NOTICE)  # the same request, concise
    assert "=== REPAIR" not in model.messages[1]  # never a repair of the cut answer
    assert not generation.report.ok


def test_a_runaway_then_a_concise_answer_tells_the_chapter():
    answer = {**story_answer("1.1"), "__complete": True}
    model = _Runaway(then=answer)
    generation = asyncio.run(
        StoryFromLessonService(model).generate_story(
            chapter_ctx(), pack("1.1", LANGUAGE), system_prompt="s"
        )
    )
    assert len(model.messages) == 2 and generation.report.ok


def test_a_runaway_pack_costs_two_calls_then_fails():
    model = _Runaway()
    with pytest.raises(TruncatedResponse):
        asyncio.run(StoryFromLessonService(model).generate_pack(chapter_ctx(), system_prompt="s"))
    assert len(model.messages) == 2 and model.messages[1].startswith(CONCISE_NOTICE)


def test_a_runaway_plan_is_made_in_code_after_two_calls():
    from app.domain.services.story_plan import StoryPlanService
    from tests.test_story_plan import request

    model = _Runaway()
    made, chosen_model, calls = asyncio.run(
        StoryPlanService(model)._make(request(), system_prompt="s", previous=None, rewritten=None)
    )
    assert (made, chosen_model, calls) == (None, None, 2)
    assert model.messages[1].startswith(CONCISE_NOTICE)


def test_the_calls_are_bounded_by_the_module_runs_deadline_inside_its_tasks():
    """The deadline set for a run reaches the pack tasks it starts (a contextvar)."""
    seen: list[float] = []

    async def pack_task() -> None:
        seen.append(call_timeout("pack"))

    async def run() -> None:
        with run_deadline(time.monotonic() + 100, time.monotonic):
            await asyncio.create_task(pack_task())

    asyncio.run(run())
    assert seen and seen[0] <= 100 - CALL_MARGIN_S


def test_story_calls_module_documents_the_choice():
    doc = story_calls.__doc__
    assert "64,000" in doc and "continuation" in doc
    # Only the Anthropic provider streams; the docstring does not claim more.
    assert "providers stream already" not in doc and "does not" in doc
