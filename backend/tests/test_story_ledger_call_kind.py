"""The AI usage ledger records the kind of every story call and whether it repairs (#2735).

Pure-unit: the ledger's session factory is mocked and the model is a fake, so
nothing here needs the shared test_engine fixture (issue #554).
"""

from __future__ import annotations

import asyncio
import contextlib
import importlib.util
import sys
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from app.ai.usage_context import current_ai_context, usage_tally
from app.domain.models.ai_usage_event import FEATURE_STORY_GENERATION, AiUsageEvent
from app.domain.services.ai_usage_service import record_ai_usage
from app.domain.services.story_calls import structured_call

_SESSION_FACTORY = "app.domain.services.ai_usage_service._session_factory_for_loop"


class _Ledger:
    """A mocked ledger session collecting the rows the recorder adds."""

    def __init__(self) -> None:
        self.rows: list[AiUsageEvent] = []
        session = MagicMock()
        session.add = MagicMock(side_effect=self.rows.append)
        session.commit = AsyncMock()
        factory = MagicMock()
        factory.return_value.__aenter__ = AsyncMock(return_value=session)
        factory.return_value.__aexit__ = AsyncMock(return_value=False)
        self.factory = MagicMock(return_value=factory)


class _Model:
    """A fake model: each call is recorded in the ledger like the provider wrapper does."""

    def __init__(self, *answers: Any, usage: dict[str, int] | None = None) -> None:
        self.answers = list(answers) or [{"ok": True}]
        self.usage = usage or {"input_tokens": 100, "output_tokens": 50}
        self.contexts: list[Any] = []

    def with_max_tokens(self, n: int):
        return self

    async def generate_structured_content(self, system, user, content_type, max_retries=1):
        self.contexts.append(current_ai_context())
        success = not isinstance(self.answers[0], BaseException)
        await record_ai_usage(
            provider="anthropic",
            model="claude-sonnet-4-6",
            operation="chat",
            usage=self.usage,
            success=success,
            feature=FEATURE_STORY_GENERATION,
        )
        answer = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        if isinstance(answer, BaseException):
            raise answer
        return answer


def _run(coro):
    return asyncio.run(coro)


def test_a_story_call_writes_its_kind_and_is_not_a_repair():
    ledger, model = _Ledger(), _Model()
    with patch(_SESSION_FACTORY, ledger.factory):
        _run(structured_call(model, "s", "u", kind="pack"))
    (row,) = ledger.rows
    assert (row.call_kind, row.is_repair) == ("pack", False)


def test_a_repair_is_recorded_under_the_kind_it_repairs_not_under_repair():
    ledger, model = _Ledger(), _Model()
    with patch(_SESSION_FACTORY, ledger.factory), usage_tally() as tally:
        _run(structured_call(model, "s", "u", kind="story", repair=True))
    (row,) = ledger.rows
    assert (row.call_kind, row.is_repair) == ("story", True)
    # The run's counters are unchanged: a repair is still counted as "repair".
    assert tally.summary() == {"repair": {"calls": 1, "output_tokens": 50}}
    assert model.contexts[0].call_kind == "repair"


def test_a_retry_that_keeps_its_kind_in_the_counters_is_flagged_in_the_ledger():
    ledger, model = _Ledger(), _Model()
    with patch(_SESSION_FACTORY, ledger.factory), usage_tally() as tally:
        _run(structured_call(model, "s", "u", kind="plan", repair_of="plan"))
    (row,) = ledger.rows
    assert (row.call_kind, row.is_repair) == ("plan", True)
    assert tally.summary() == {"plan": {"calls": 1, "output_tokens": 50}}


def test_a_failed_call_still_carries_its_kind():
    ledger, model = _Ledger(), _Model(RuntimeError("boom"))
    with patch(_SESSION_FACTORY, ledger.factory), contextlib.suppress(RuntimeError):
        _run(structured_call(model, "s", "u", kind="rally"))
    (row,) = ledger.rows
    assert (row.call_kind, row.is_repair, row.success) == ("rally", False, False)


def test_the_context_does_not_leak_past_the_call():
    ledger, model = _Ledger(), _Model()
    with patch(_SESSION_FACTORY, ledger.factory):
        _run(structured_call(model, "s", "u", kind="story", repair=True))
        assert current_ai_context().repair_of is None


def test_a_call_outside_a_story_run_has_no_kind():
    ledger = _Ledger()
    with patch(_SESSION_FACTORY, ledger.factory):
        _run(record_ai_usage(provider="openai", model="gpt-image-1", operation="image"))
    (row,) = ledger.rows
    assert row.call_kind is None and row.is_repair is False


def test_the_plans_second_attempt_is_a_flagged_repair_and_the_first_is_not():
    from app.domain.services.story_plan import StoryPlanService
    from tests.test_story_plan import answer, request

    ledger = _Ledger()
    model = _Model(ValueError("unreadable"), {**answer(), "__complete": True})
    with patch(_SESSION_FACTORY, ledger.factory), usage_tally() as tally:
        _run(
            StoryPlanService(model)._make(
                request(), system_prompt="s", previous=None, rewritten=None
            )
        )
    assert [(r.call_kind, r.is_repair) for r in ledger.rows] == [("plan", False), ("plan", True)]
    assert tally.summary()["plan"]["calls"] == 2 and "repair" not in tally.summary()


def test_the_bibles_retry_is_a_flagged_repair_and_the_first_call_is_not():
    from app.domain.services.story_bible import StoryBibleService
    from tests.test_story_bible import MODULE, course

    ledger = _Ledger()
    model = _Model({"raw_response": True}, {"cast": [{"id": "mentor", "name": "Zida"}]})
    service = StoryBibleService(model)
    with patch(_SESSION_FACTORY, ledger.factory), usage_tally() as tally:
        _run(service._call(course(), [MODULE], is_kids=False, country="BF"))
    assert [(r.call_kind, r.is_repair) for r in ledger.rows] == [("bible", False), ("bible", True)]
    assert tally.summary()["bible"]["calls"] == 2 and "repair" not in tally.summary()


# ---------------------------------------------------------------- the report


def _report():
    path = Path(__file__).parent.parent / "scripts" / "report_story_costs.py"
    spec = importlib.util.spec_from_file_location("report_story_costs", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["report_story_costs"] = module
    spec.loader.exec_module(module)
    return module


def _event(kind, out, *, repair=False, ok=True, inp=1000, cents=10.0):
    return {
        "call_kind": kind,
        "is_repair": repair,
        "success": ok,
        "input_tokens": inp,
        "output_tokens": out,
        "cost_cents": cents,
    }


def test_the_report_groups_by_kind_with_repairs_apart_and_totals_match():
    report = _report()
    events = [
        _event("story", 6000),
        _event("story", 6000),
        _event("story", 6000, ok=False),
        _event("story", 10000, repair=True),
        _event("rally", 6000),
        _event(None, 2000),
    ]
    lines = {line["kind"]: line for line in report.build_report(events)}
    assert lines["story"]["calls"] == 3 and lines["story"]["failed"] == 1
    assert lines["story"]["output_tokens"] == 18000 and lines["story"]["mean_output"] == 6000
    assert lines["story (repair)"]["calls"] == 1
    assert lines["story (repair)"]["repair_rate"] == "0.33"
    assert lines["rally"]["calls"] == 1 and "rally (repair)" not in lines
    assert lines["(no kind)"]["output_tokens"] == 2000
    assert lines["TOTAL"]["output_tokens"] == sum(e["output_tokens"] for e in events)
    assert lines["TOTAL"]["calls"] == 6 and lines["TOTAL"]["cost_usd"] == "0.6000"


def test_the_report_renders_text_and_markdown():
    report = _report()
    rows = report.build_report([_event("pack", 1500)])
    assert "output tokens" in report.format_table(rows)
    assert report.format_table(rows, markdown=True).startswith("| kind |")


def test_the_report_selects_only_story_rows_of_the_module():
    import uuid

    report = _report()
    session = MagicMock()
    result = MagicMock()
    result.all.return_value = []
    session.execute = AsyncMock(return_value=result)
    _run(report.collect(session, uuid.uuid4()))
    sql = str(session.execute.call_args[0][0])
    assert "ai_usage_events.feature" in sql and "ai_usage_events.module_id" in sql
    assert sql.lstrip().upper().startswith("SELECT")
