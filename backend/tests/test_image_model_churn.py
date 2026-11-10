"""OpenAI image model churn (#2689): gpt-image-1 was shut down on 2026-10-23.

Every call goes to a mocked ``AsyncOpenAI``; no network, no paid call.
"""

from __future__ import annotations

import base64
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import openai
import pytest

from app.ai.providers import image_provider
from app.ai.providers.image_provider import (
    DEFAULT_IMAGE_MODEL,
    PLAIN_BACKGROUND,
    edit_image,
    generate_image,
    is_model_error,
    refused_param,
    resolve_image_provider,
    unsupported_params,
)
from app.domain.services import story_art_service as svc
from app.infrastructure.config.image_models import IMAGE_MODEL_OPTIONS, OPENAI_IMAGE_MODEL
from app.infrastructure.config.platform_defaults import DEFAULTS_BY_KEY
from tests.test_story_art import (
    GIRL,
    MARKET,
    FakeImages,
    FakeSessions,
    ready_rows,
    row,
    run_generator,
)

NOW = datetime(2026, 11, 10, 9, 0, tzinfo=UTC)


def _api_error(cls, status: int, **body: Any):
    response = httpx.Response(status, request=httpx.Request("POST", "https://api.test/images"))
    return cls(body.get("message", "refused"), response=response, body=body)


def model_missing(model: str = "gpt-image-1"):
    return _api_error(
        openai.BadRequestError,
        400,
        message=f"The model '{model}' does not exist.",
        type="image_generation_user_error",
        param="model",
        code="invalid_value",
    )


def param_refused(param: str, code: str = "unknown_parameter"):
    return _api_error(openai.BadRequestError, 400, param=param, code=code)


def _response(payload: bytes = b"IMG") -> MagicMock:
    response = MagicMock()
    response.data = [MagicMock(b64_json=base64.b64encode(payload).decode())]
    response.usage = None
    return response


def _settings(*, google: str = "", openai_key: str = "ok") -> SimpleNamespace:
    return SimpleNamespace(
        google_api_key=google,
        openai_api_key=openai_key,
        gemini_openai_base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
    )


@pytest.fixture(autouse=True)
def fresh_process_memory():
    """Each test starts with what a fresh process knows."""
    retired = dict(image_provider._RETIRED_IMAGE_MODELS)
    unsupported = {k: set(v) for k, v in image_provider._UNSUPPORTED_PARAMS.items()}
    image_provider._UNSUPPORTED_PARAMS.clear()
    yield
    image_provider._RETIRED_IMAGE_MODELS.clear()
    image_provider._RETIRED_IMAGE_MODELS.update(retired)
    image_provider._UNSUPPORTED_PARAMS.clear()
    image_provider._UNSUPPORTED_PARAMS.update(unsupported)


@pytest.fixture
def openai_client():
    client = MagicMock()
    client.images.generate = AsyncMock(return_value=_response(b"GEN"))
    client.images.edit = AsyncMock(return_value=_response(b"EDIT"))
    client.with_options.return_value = client
    with (
        patch("app.ai.providers.image_provider.AsyncOpenAI", return_value=client),
        patch("app.ai.providers.image_provider.get_settings", return_value=_settings()),
    ):
        yield client


@pytest.fixture
def ledger():
    with patch(
        "app.domain.services.ai_usage_service.record_ai_usage", new_callable=AsyncMock
    ) as record:
        yield record


def _rows(ledger) -> list[dict]:
    return [call.kwargs for call in ledger.await_args_list]


# --------------------------------------------------------------------------
# The model id
# --------------------------------------------------------------------------


class TestModelId:
    def test_the_current_openai_model_is_the_default_and_the_fallback(self):
        assert OPENAI_IMAGE_MODEL == "gpt-image-2.6-sunburst"
        assert DEFAULT_IMAGE_MODEL == OPENAI_IMAGE_MODEL
        assert image_provider._FALLBACK_IMAGE_MODEL == OPENAI_IMAGE_MODEL

    def test_the_admin_setting_defaults_to_it_and_offers_the_current_models(self):
        setting = DEFAULTS_BY_KEY["ai-model-image"]
        assert setting.default == OPENAI_IMAGE_MODEL
        assert setting.allowed_options == list(IMAGE_MODEL_OPTIONS)
        assert {
            "gpt-image-2.6-sunburst",
            "gpt-image-2.6-flare",
            "gpt-image-2.5-sunburst",
            "gemini-2.5-flash-image",
        } == set(setting.allowed_options)
        assert "gpt-image-1" not in setting.allowed_options

    def test_no_model_resolves_to_the_current_one(self, openai_client):
        assert resolve_image_provider(None).model == OPENAI_IMAGE_MODEL

    async def test_a_stored_gpt_image_1_setting_draws_with_the_successor(
        self, openai_client, ledger
    ):
        # A staging or prod setting may still say gpt-image-1: it keeps working.
        _, used = await generate_image("p", model="gpt-image-1")
        assert used == OPENAI_IMAGE_MODEL
        (call,) = openai_client.images.generate.call_args_list
        assert call.kwargs["model"] == OPENAI_IMAGE_MODEL


# --------------------------------------------------------------------------
# Error recognition
# --------------------------------------------------------------------------


class TestErrorRecognition:
    def test_a_model_that_does_not_exist_is_a_model_error(self):
        assert is_model_error(model_missing())
        assert is_model_error(
            _api_error(openai.NotFoundError, 404, param="model", code="model_not_found")
        )
        assert is_model_error(_api_error(openai.NotFoundError, 404, code="model_not_found"))

    def test_other_refusals_are_not_model_errors(self):
        assert not is_model_error(param_refused("background"))
        assert not is_model_error(_api_error(openai.BadRequestError, 400, code="moderation"))
        assert not is_model_error(RuntimeError("x"))

    @pytest.mark.parametrize(
        "param", ["background", "input_fidelity", "quality", "output_format", "size"]
    )
    @pytest.mark.parametrize(
        "code", ["invalid_value", "unknown_parameter", "unsupported_parameter"]
    )
    def test_a_droppable_parameter_refused(self, param, code):
        assert refused_param(param_refused(param, code)) == param

    def test_other_parameters_or_codes_are_not_dropped(self):
        assert refused_param(param_refused("prompt")) is None
        assert refused_param(param_refused("background", code="moderation_blocked")) is None
        assert refused_param(model_missing()) is None


# --------------------------------------------------------------------------
# Parameter compatibility
# --------------------------------------------------------------------------


class TestParameterCompatibility:
    async def test_a_refused_background_is_dropped_and_the_call_tried_once_more(
        self, openai_client, ledger
    ):
        openai_client.images.generate.side_effect = [param_refused("background"), _response()]
        data, used = await generate_image(
            "a girl", model=OPENAI_IMAGE_MODEL, size="1024x1536", background="transparent"
        )
        assert (data, used) == (b"IMG", OPENAI_IMAGE_MODEL)
        first, second = (c.kwargs for c in openai_client.images.generate.call_args_list)
        assert first["background"] == "transparent"
        assert "background" not in second
        # No transparency: a plain one-colour background the flood fill clears.
        assert second["prompt"] == "a girl" + PLAIN_BACKGROUND
        assert unsupported_params(OPENAI_IMAGE_MODEL) == {"background"}
        rows = _rows(ledger)
        assert [r.get("success", True) for r in rows] == [False, True]
        assert rows[0]["error_type"] == "BadRequestError" and rows[1]["images_count"] == 1

    async def test_the_model_is_remembered_and_never_sent_it_again(self, openai_client, ledger):
        openai_client.images.generate.side_effect = [param_refused("background"), _response()]
        await generate_image("x", model=OPENAI_IMAGE_MODEL, background="transparent")
        openai_client.images.generate.side_effect = None
        openai_client.images.generate.reset_mock()
        await generate_image("y", model=OPENAI_IMAGE_MODEL, background="transparent")
        (call,) = openai_client.images.generate.call_args_list
        assert "background" not in call.kwargs
        assert call.kwargs["prompt"] == "y" + PLAIN_BACKGROUND

    async def test_a_refused_input_fidelity_is_dropped_from_edits(self, openai_client, ledger):
        openai_client.images.edit.side_effect = [
            param_refused("input_fidelity", "unsupported_parameter"),
            _response(b"EDIT"),
        ]
        data, _ = await edit_image("p", b"REF", model=OPENAI_IMAGE_MODEL, background="transparent")
        assert data == b"EDIT"
        first, second = (c.kwargs for c in openai_client.images.edit.call_args_list)
        assert first["input_fidelity"] == "high" and "input_fidelity" not in second
        assert second["background"] == "transparent"  # only the refused one goes

    @pytest.mark.parametrize("param", ["quality", "size", "output_format"])
    async def test_other_droppable_parameters(self, openai_client, ledger, param):
        openai_client.images.generate.side_effect = [
            param_refused(param, "invalid_value"),
            _response(),
        ]
        await generate_image("p", model=OPENAI_IMAGE_MODEL, background="opaque")
        second = openai_client.images.generate.call_args_list[1].kwargs
        assert param not in second

    async def test_only_one_retry_and_a_second_refusal_is_remembered(self, openai_client, ledger):
        openai_client.images.edit.side_effect = [
            param_refused("background"),
            param_refused("input_fidelity"),
        ]
        with pytest.raises(openai.BadRequestError):
            await edit_image("p", b"REF", model=OPENAI_IMAGE_MODEL, background="transparent")
        assert openai_client.images.edit.await_count == 2
        assert [r["success"] for r in _rows(ledger)] == [False, False]
        assert unsupported_params(OPENAI_IMAGE_MODEL) == {"background", "input_fidelity"}

    async def test_an_undroppable_refusal_is_not_retried(self, openai_client, ledger):
        openai_client.images.generate.side_effect = [param_refused("prompt")]
        with pytest.raises(openai.BadRequestError):
            await generate_image("p", model=OPENAI_IMAGE_MODEL)
        assert openai_client.images.generate.await_count == 1
        assert unsupported_params(OPENAI_IMAGE_MODEL) == set()


# --------------------------------------------------------------------------
# A model OpenAI does not know
# --------------------------------------------------------------------------


class TestModelFallback:
    async def test_a_configured_model_openai_lost_falls_back_and_is_remembered(
        self, openai_client, ledger
    ):
        openai_client.images.generate.side_effect = [
            model_missing("gpt-image-1.5"),
            _response(b"OK"),
        ]
        data, used = await generate_image("p", model="gpt-image-1.5")
        assert (data, used) == (b"OK", OPENAI_IMAGE_MODEL)
        models = [c.kwargs["model"] for c in openai_client.images.generate.call_args_list]
        assert models == ["gpt-image-1.5", OPENAI_IMAGE_MODEL]
        assert [(r["model"], r.get("success", True)) for r in _rows(ledger)] == [
            ("gpt-image-1.5", False),
            (OPENAI_IMAGE_MODEL, True),
        ]
        # Remembered for the process: the next call goes straight to the successor.
        assert resolve_image_provider("gpt-image-1.5").model == OPENAI_IMAGE_MODEL

    async def test_the_current_model_missing_too_is_raised_not_looped(self, openai_client, ledger):
        openai_client.images.generate.side_effect = [model_missing(OPENAI_IMAGE_MODEL)]
        with pytest.raises(openai.BadRequestError):
            await generate_image("p", model=OPENAI_IMAGE_MODEL)
        assert openai_client.images.generate.await_count == 1

    async def test_another_openai_failure_does_not_fall_back(self, openai_client, ledger):
        openai_client.images.generate.side_effect = [
            _api_error(openai.RateLimitError, 429, code="rate_limit_exceeded")
        ]
        with pytest.raises(openai.RateLimitError):
            await generate_image("p", model="gpt-image-2.6-flare")
        assert openai_client.images.generate.await_count == 1


# --------------------------------------------------------------------------
# Story art: configuration failures, the model in the redraw rule, ART_VERSION
# --------------------------------------------------------------------------


class TestConfigurationFailures:
    def test_a_missing_model_is_a_configuration_failure_never_final(self):
        failure = svc.classify_failure(model_missing(), None, MARKET.digest, now=NOW)
        assert failure.error.startswith("configuration: BadRequestError")
        assert failure.retry_after == NOW + svc.CONFIG_RETRY_AFTER == NOW + timedelta(hours=1)
        assert failure.failed_runs == 0
        # However many runs in a row, it is never given up.
        previous = row(
            MARKET, "backdrop", status="failed", failed_runs=3, retry_after=NOW - timedelta(1)
        )
        again = svc.classify_failure(model_missing(), previous, MARKET.digest, now=NOW)
        assert again.retry_after is not None and again.failed_runs == 0

    def test_it_waits_an_hour_or_a_model_change(self):
        failed = row(MARKET, "backdrop", status="failed", retry_after=NOW + timedelta(hours=1))
        failed.model = "gpt-image-1"
        accepted = {MARKET.digest: MARKET.look}
        assert svc.row_state(failed, accepted, now=NOW, model="gpt-image-1") == "failed"
        assert svc.row_state(failed, accepted, now=NOW, model=OPENAI_IMAGE_MODEL) == "outstanding"
        later = NOW + timedelta(hours=1)
        assert svc.row_state(failed, accepted, now=later, model="gpt-image-1") == "outstanding"

    def test_a_model_change_never_redraws_ready_art(self):
        ready = ready_rows([MARKET])[0]
        ready.model = "gpt-image-1"
        assert (
            svc.row_state(ready, {MARKET.digest: MARKET.look}, now=NOW, model=OPENAI_IMAGE_MODEL)
            == "ready"
        )

    def test_a_final_failure_gets_one_new_chance_with_a_new_model(self):
        final = row(MARKET, "backdrop", status="failed")
        final.model = "gpt-image-2.5-sunburst"
        assert svc.plan_art([MARKET], [final], now=NOW, model="gpt-image-2.5-sunburst") == []
        assert svc.plan_art([MARKET], [final], now=NOW, model=OPENAI_IMAGE_MODEL) == [
            svc.ArtJob(MARKET, ("backdrop",))
        ]

    async def test_a_run_tries_a_missing_model_once_and_stores_it_for_retry(self):
        images = FakeImages(errors={"market look": [model_missing(), model_missing()]})
        before = datetime.now(UTC)
        report, images, sessions = await run_generator([MARKET], images=images)
        assert len(images.calls) == 1  # no second attempt: the same model fails the same way
        art = sessions.by_item()[("market", "backdrop")]
        assert art.status == "failed" and art.failed_runs == 0
        assert art.error.startswith("configuration:")
        assert art.model == OPENAI_IMAGE_MODEL  # the configured model it failed under
        assert timedelta(minutes=59) <= art.retry_after - before <= timedelta(hours=1, minutes=1)
        assert report["failed"] == 1


class TestArtVersionBump:
    def test_the_version_is_bumped_for_the_rows_gpt_image_1_failed(self):
        assert svc.ART_VERSION == 2

    def test_v1_failures_are_drawn_once_then_never_again(self):
        # Staging: all 32 v1 rows failed for good under gpt-image-1.
        v1_failed = [row(GIRL, pose, status="failed", art_version=1) for pose in GIRL.poses] + [
            row(MARKET, "backdrop", status="failed", art_version=1)
        ]
        jobs = svc.plan_art([GIRL, MARKET], v1_failed, now=NOW, model=OPENAI_IMAGE_MODEL)
        assert {job.item.key: job.poses for job in jobs} == {
            "hero:girl": GIRL.poses,
            "market": ("backdrop",),
        }
        # Drawn at v2: nothing more.
        assert svc.plan_art([GIRL, MARKET], ready_rows([GIRL, MARKET]), now=NOW) == []

    async def test_a_run_stores_the_new_version(self):
        _, _, sessions = await run_generator([MARKET], sessions=FakeSessions())
        assert {art.art_version for art in sessions.written} == {2}
