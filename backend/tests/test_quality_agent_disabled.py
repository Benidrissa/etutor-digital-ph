"""Unit tests for the quality-agent 'disabled' switch (#2639) — pure, no DB."""

from unittest.mock import MagicMock, patch

import pytest

from app.infrastructure.config.platform_defaults import SETTING_DEFINITIONS


def _mock_settings_cache(value: str):
    cache = MagicMock()
    cache.get.return_value = value
    return patch(
        "app.domain.services.platform_settings_service.SettingsCache.instance",
        return_value=cache,
    )


def test_disabled_is_an_allowed_option():
    defn = next(d for d in SETTING_DEFINITIONS if d.key == "ai-model-quality")
    assert "disabled" in defn.allowed_options
    # Default unchanged — other tenants keep the auditor on.
    assert defn.default == "claude-sonnet-4-6"


def test_quality_disabled_helper():
    from app.tasks.quality_assessment import _quality_disabled

    with _mock_settings_cache("disabled"):
        assert _quality_disabled() is True
    with _mock_settings_cache("claude-sonnet-4-6"):
        assert _quality_disabled() is False


def test_unit_tasks_skip_when_disabled():
    from app.tasks.quality_assessment import (
        assess_and_regenerate_unit_task,
        assess_course_structure_task,
        assess_unit_task,
        extract_course_glossary_task,
    )

    with _mock_settings_cache("disabled"):
        for task, kwargs in (
            (assess_unit_task, {"content_id": "x"}),
            (assess_and_regenerate_unit_task, {"content_id": "x"}),
            (extract_course_glossary_task, {"course_id": "x"}),
            (assess_course_structure_task, {"course_id": "x"}),
        ):
            result = task.run(**kwargs)
            assert result["status"] == "skipped"
            assert result["reason"] == "quality_agent_disabled"


def test_course_task_cancels_run_when_disabled():
    from app.tasks import quality_assessment as qa

    async def _noop(run_id, reason):
        _noop.called = (run_id, reason)

    with _mock_settings_cache("disabled"), patch.object(qa, "_mark_run_cancelled", _noop):
        result = qa.assess_course_task.run(run_id="11111111-1111-1111-1111-111111111111")
    assert result["status"] == "skipped"
    assert _noop.called[0] == "11111111-1111-1111-1111-111111111111"


@pytest.mark.asyncio
async def test_assess_course_raises_when_disabled():
    import uuid

    from app.domain.services.quality_agent_service import (
        CourseQualityService,
        QualityAgentDisabledError,
    )

    service = CourseQualityService.__new__(CourseQualityService)  # skip __init__
    with _mock_settings_cache("disabled"), pytest.raises(QualityAgentDisabledError):
        await service.assess_course(
            course_id=uuid.uuid4(),
            triggered_by_user_id=None,
            session=MagicMock(),
        )
