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

    @pytest.mark.parametrize("option", list(IMAGE_MODEL_OPTIONS))
    def test_a_stored_retired_value_can_be_replaced_by_any_option(self, option):
        # Saving validates only the new value: whatever is stored (gpt-image-1),
        # any offered model is accepted, and the retired one is refused.
        from app.domain.services.platform_settings_service import _validate_value

        setting = DEFAULTS_BY_KEY["ai-model-image"]
        assert _validate_value(setting, option) == option
        with pytest.raises(ValueError, match="must be one of"):
            _validate_value(setting, "gpt-image-1")

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
        "code", ["invalid_value", "unknown_parameter", "unsupported_parameter", "unsupported_value"]
    )
    def test_a_droppable_parameter_refused(self, param, code):
        assert refused_param(param_refused(param, code)) == param

    def test_other_parameters_or_codes_are_not_dropped(self):
        assert refused_param(param_refused("prompt")) is None
        assert refused_param(param_refused("background", code="moderation_blocked")) is None
        assert refused_param(model_missing()) is None  # param=model: a model error

    def test_a_droppable_param_is_a_refusal_whatever_the_code(self):
        # #2696: staging's code was invalid_input_fidelity_model, unknown to the list.
        for code in ("invalid_input_fidelity_model", "invalid_value", None):
            assert refused_param(param_refused("input_fidelity", code=code)) == "input_fidelity"

    @pytest.mark.parametrize(
        "code",
        [
            "moderation_blocked",
            "content_policy_violation",
            "safety",
            "image_moderation_failed",
            "usage_policy_block",
        ],
    )
    def test_a_safety_block_is_never_a_refusal(self, code):
        # Even when it names a droppable parameter: it stays final.
        exc = param_refused("background", code=code)
        assert refused_param(exc) is None
        assert not svc.failure_is_transient(exc)
        failure = svc.classify_failure(exc, None, MARKET.digest, now=NOW)
        assert failure.retry_after is None and failure.failed_runs == 0
        assert image_provider.refused_param_in_error(svc._error_text(exc)) is None


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
        assert second["prompt"] == "a girl" + PLAIN_BACKGROUND  # no wording to replace
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

    async def test_each_refused_parameter_is_dropped_in_turn(self, openai_client, ledger):
        openai_client.images.edit.side_effect = [
            param_refused("background"),
            param_refused("input_fidelity", "unsupported_value"),
            _response(b"EDIT"),
        ]
        data, _ = await edit_image("p", b"REF", model=OPENAI_IMAGE_MODEL, background="transparent")
        assert data == b"EDIT"
        assert openai_client.images.edit.await_count == 3
        last = openai_client.images.edit.call_args_list[-1].kwargs
        assert "background" not in last and "input_fidelity" not in last
        assert [r.get("success", True) for r in _rows(ledger)] == [False, False, True]
        assert unsupported_params(OPENAI_IMAGE_MODEL) == {"background", "input_fidelity"}

    async def test_the_retries_are_bounded_by_the_droppable_parameters(self, openai_client, ledger):
        # Every droppable parameter refused in turn: one retry each, then the
        # image is drawn with none of them.
        refusals = [param_refused(p) for p in ("background", "output_format", "quality", "size")]
        openai_client.images.generate.side_effect = [*refusals, _response(b"OK")]
        data, _ = await generate_image("p", model=OPENAI_IMAGE_MODEL, background="transparent")
        assert data == b"OK" and openai_client.images.generate.await_count == 5
        last = openai_client.images.generate.call_args_list[-1].kwargs
        assert set(last) == {"model", "prompt"}

    async def test_a_refusal_of_a_parameter_not_sent_is_not_retried(self, openai_client, ledger):
        image_provider._UNSUPPORTED_PARAMS[OPENAI_IMAGE_MODEL] = {"quality"}
        openai_client.images.generate.side_effect = [param_refused("quality")]
        with pytest.raises(openai.BadRequestError):
            await generate_image("p", model=OPENAI_IMAGE_MODEL)
        assert openai_client.images.generate.await_count == 1

    async def test_concurrent_calls_refused_for_one_parameter_all_retry(
        self, openai_client, ledger
    ):
        # Story art draws 3 images at once: all three send `quality` and are
        # refused; the first to handle it remembers it, and the other two must
        # still retry (their own request sent it), not fail.
        import asyncio

        async def generate(**kwargs):
            await asyncio.sleep(0.01)
            if "quality" in kwargs:
                raise param_refused("quality", "invalid_value")
            return _response(b"OK")

        openai_client.images.generate.side_effect = generate
        results = await asyncio.gather(
            *(generate_image(f"p{i}", model=OPENAI_IMAGE_MODEL) for i in range(3)),
            return_exceptions=True,
        )
        assert all(result == (b"OK", OPENAI_IMAGE_MODEL) for result in results), results
        assert openai_client.images.generate.await_count == 6

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


# --------------------------------------------------------------------------
# One background instruction when transparency is refused (round 4, item 3)
# --------------------------------------------------------------------------


class TestPlainBackgroundPrompt:
    @pytest.mark.parametrize(
        "prompt",
        [svc.character_prompt("a teacher"), svc.pose_prompt("a teacher", "talk")],
        ids=["idle", "pose"],
    )
    def test_the_transparent_wording_is_replaced_not_contradicted(self, prompt):
        assert "transparent background" in prompt.lower()
        plain = image_provider.plain_background_prompt(prompt)
        assert "transparent" not in plain.lower()
        assert plain.lower().count("plain flat solid light-grey background") >= 1
        assert "a teacher" in plain

    def test_a_prompt_without_the_wording_gets_the_plain_sentence(self):
        assert image_provider.plain_background_prompt("a girl") == "a girl" + PLAIN_BACKGROUND

    async def test_a_refused_background_sends_one_background_instruction(
        self, openai_client, ledger
    ):
        image_provider._UNSUPPORTED_PARAMS[OPENAI_IMAGE_MODEL] = {"background"}
        prompt = svc.character_prompt("a teacher")
        await generate_image(prompt, model=OPENAI_IMAGE_MODEL, background="transparent")
        sent = openai_client.images.generate.call_args.kwargs["prompt"]
        assert "transparent" not in sent.lower()
        assert "background" not in openai_client.images.generate.call_args.kwargs


# --------------------------------------------------------------------------
# Classifying a failure by the whole chain (round 4, items 1-2)
# --------------------------------------------------------------------------


class TestChainClassification:
    async def _gemini_then_openai(self, openai_client, first: Exception, second: Exception):
        """A Gemini backdrop failing with ``first``, its OpenAI fallback with ``second``."""
        openai_client.images.generate.side_effect = [first, second]
        with (
            patch(
                "app.ai.providers.image_provider.get_settings",
                return_value=_settings(google="gk"),
            ),
            pytest.raises(Exception) as raised,
        ):
            await generate_image("p", model="gemini-2.5-flash-image")
        return raised.value

    async def test_a_billed_primary_failure_is_not_a_configuration_failure(
        self, openai_client, ledger
    ):
        timeout = openai.APITimeoutError(request=httpx.Request("POST", "https://g.test"))
        exc = await self._gemini_then_openai(openai_client, timeout, model_missing())
        assert exc.image_primary_error is timeout
        assert not svc.failure_is_config(exc)
        failure = svc.classify_failure(exc, None, MARKET.digest, now=NOW)
        # Judged as the primary's timeout: one later run, then final.
        assert not failure.error.startswith("configuration")
        assert failure.error.startswith("APITimeoutError")
        assert failure.failed_runs == 1 and failure.retry_after == NOW + timedelta(hours=1)
        previous = row(
            MARKET, "backdrop", status="failed", failed_runs=1, retry_after=NOW - timedelta(1)
        )
        assert svc.classify_failure(exc, previous, MARKET.digest, now=NOW).retry_after is None

    async def test_model_errors_all_along_are_a_configuration_failure(self, openai_client, ledger):
        exc = await self._gemini_then_openai(
            openai_client,
            _api_error(openai.NotFoundError, 404, code="model_not_found"),
            model_missing(OPENAI_IMAGE_MODEL),
        )
        assert svc.failure_is_config(exc)
        assert svc.classify_failure(exc, None, MARKET.digest, now=NOW).error.startswith(
            "configuration"
        )

    def test_a_refused_parameter_is_not_final(self):
        exc = param_refused("input_fidelity", "unsupported_value")
        failure = svc.classify_failure(exc, None, GIRL.digest, now=NOW)
        assert failure.retry_after == NOW + svc.PARAM_RETRY_AFTER
        assert failure.failed_runs == 1
        # Bounded: once every droppable parameter could have been dropped, final.
        previous = row(
            GIRL,
            "talk",
            status="failed",
            failed_runs=len(image_provider.DROPPABLE_PARAMS),
            retry_after=NOW - timedelta(1),
        )
        assert svc.classify_failure(exc, previous, GIRL.digest, now=NOW).retry_after is None


# --------------------------------------------------------------------------
# #2696: the input_fidelity refusal staging hit, and its 18 final rows
# --------------------------------------------------------------------------

#: The error staging stored for each of the 18 pose edits.
STAGING_REFUSAL = {
    "message": "The model 'gpt-image-2.6-sunburst' does not support the 'input_fidelity' parameter.",
    "type": "image_generation_user_error",
    "param": "input_fidelity",
    "code": "invalid_input_fidelity_model",
}


def staging_refusal(body: dict | None = None) -> openai.BadRequestError:
    """The refusal as the SDK raises it: the message embeds the error body."""
    inner = body or STAGING_REFUSAL
    response = httpx.Response(400, request=httpx.Request("POST", "https://api.test/edits"))
    return openai.BadRequestError(
        f"Error code: 400 - {{'error': {inner!r}}}", response=response, body=inner
    )


def legacy_row(item, pose: str) -> SimpleNamespace:
    """A pose stored as a final failure before #2696, exactly as on staging."""
    stored = row(item, pose, status="failed")
    stored.error = svc._error_text(staging_refusal())
    stored.model = "gemini-2.5-flash-image"
    return stored


FRIEND = svc.ArtItem("character", "friend", "friend look")
FAMILY = svc.ArtItem("character", "family", "family look")
MENTOR_2696 = svc.ArtItem("character", "mentor", "mentor look")
MARGO_2696 = svc.ArtItem("character", "margo", "margo look")
BOY_2696 = svc.ArtItem("character", "hero:boy", "boy look")
CAST_2696 = [GIRL, BOY_2696, FRIEND, MENTOR_2696, FAMILY, MARGO_2696]
PLACES_2696 = [svc.ArtItem("place", f"place{i}", f"place {i}") for i in range(8)]


def staging_rows() -> list[SimpleNamespace]:
    """Staging after #2691: 8 backdrops and 6 idles ready, 18 poses failed for good."""
    rows = ready_rows(PLACES_2696)
    for item in CAST_2696:
        rows += [row(item, "idle")] + [legacy_row(item, p) for p in svc.CHARACTER_POSES[1:]]
    return rows


class TestInputFidelityRefusal:
    def test_the_staging_error_is_a_refused_parameter_not_a_model_error(self):
        exc = staging_refusal()
        assert refused_param(exc) == "input_fidelity"
        assert not is_model_error(exc)

    @pytest.mark.parametrize(
        ("message", "param"),
        [
            ("The model 'x' does not support the 'input_fidelity' parameter.", "input_fidelity"),
            ("Unknown parameter: 'quality'.", "quality"),
            ("Unsupported parameter: 'background' is not supported with this model.", "background"),
            ("Unsupported value: 'size' does not support '4096x4096' with this model.", "size"),
        ],
    )
    def test_the_message_names_the_parameter_when_param_is_missing(self, message, param):
        exc = staging_refusal({"message": message, "type": "invalid_request_error"})
        assert refused_param(exc) == param

    def test_a_message_naming_no_droppable_parameter_is_no_refusal(self):
        missing = staging_refusal(
            {"message": "The model 'gpt-image-1' does not exist.", "type": "invalid_request_error"}
        )
        assert refused_param(missing) is None
        prompt = staging_refusal({"message": "Unknown parameter: 'prompt'."})
        assert refused_param(prompt) is None

    async def test_an_edit_refused_input_fidelity_is_retried_without_it(
        self, openai_client, ledger
    ):
        openai_client.images.edit.side_effect = [staging_refusal(), _response(b"EDIT")]
        data, used = await edit_image(
            "p", b"REF", model="gemini-2.5-flash-image", background="transparent"
        )
        assert (data, used) == (b"EDIT", OPENAI_IMAGE_MODEL)  # edits route to OpenAI
        first, second = (c.kwargs for c in openai_client.images.edit.call_args_list)
        assert first["input_fidelity"] == "high" and "input_fidelity" not in second
        assert unsupported_params(OPENAI_IMAGE_MODEL) == {"input_fidelity"}

    def test_a_stored_failure_is_read_back(self):
        read = image_provider.refused_param_in_error
        assert read(legacy_row(GIRL, "talk").error) == "input_fidelity"
        assert read(svc._error_text(model_missing())) is None
        assert read("idle pose unavailable") is None
        assert read("RuntimeError: boom") is None
        assert read(None) is None


class TestStoredRefusalsRedrawnOnce:
    ACCEPTED = {GIRL.digest: GIRL.look}

    def test_a_refusal_stored_as_final_is_outstanding_again(self):
        stored = legacy_row(GIRL, "talk")
        assert svc.row_state(stored, self.ACCEPTED, now=NOW, model=stored.model) == "outstanding"

    def test_once_reclassified_it_follows_the_normal_rules(self):
        # The redraw failed again on the refusal: stored the new way it waits
        # (failed_runs >= 1), and once given up it is final for good.
        previous = legacy_row(GIRL, "talk")
        again = svc.classify_failure(staging_refusal(), previous, GIRL.digest, now=NOW)
        assert again.failed_runs == 1 and again.retry_after == NOW + svc.PARAM_RETRY_AFTER
        waiting = row(GIRL, "talk", status="failed", failed_runs=1, retry_after=again.retry_after)
        waiting.error = again.error
        assert svc.row_state(waiting, self.ACCEPTED, now=NOW) == "failed"
        given_up = row(GIRL, "talk", status="failed", failed_runs=6, retry_after=None)
        given_up.error = again.error
        assert svc.row_state(given_up, self.ACCEPTED, now=NOW) == "failed"

    def test_other_final_failures_stay_final(self):
        refused_prompt = row(GIRL, "talk", status="failed")
        refused_prompt.error = svc._error_text(
            staging_refusal({"message": "Your request was rejected by the safety system."})
        )
        assert svc.row_state(refused_prompt, self.ACCEPTED, now=NOW) == "failed"

    def test_staging_plans_exactly_the_18_pose_edits(self):
        rows = staging_rows()
        jobs = svc.plan_art(CAST_2696 + PLACES_2696, rows, now=NOW, model="gemini-2.5-flash-image")
        assert sum(job.cost for job in jobs) == 18
        assert all(job.idle_row_id is not None for job in jobs)  # edits of the stored idles
        assert {job.poses for job in jobs} == {svc.CHARACTER_POSES[1:]}
        assert {job.item.key for job in jobs} == {item.key for item in CAST_2696}

    def test_the_ready_rows_are_never_redrawn(self):
        rows = staging_rows()
        jobs = svc.plan_art(CAST_2696 + PLACES_2696, rows, now=NOW, model="gemini-2.5-flash-image")
        planned = {(job.item.key, pose) for job in jobs for pose in job.poses}
        ready = {(r.key, r.pose) for r in rows if r.status == "ready"}
        assert len(ready) == 14 and not planned & ready

    async def test_a_run_draws_the_18_edits_then_nothing(self):
        from tests.test_story_art import figure_png

        idle_webp, _, _ = svc.process_character(figure_png())
        rows = staging_rows()
        for stored in rows:
            # As on staging, the rows failed under the model the run uses: no
            # model change reopens them, only the stored-refusal rule does.
            stored.model = OPENAI_IMAGE_MODEL
        report, images, sessions = await run_generator(
            CAST_2696 + PLACES_2696, rows, sessions=FakeSessions(idle_webp=idle_webp)
        )
        assert [call.kind for call in images.calls] == ["edit"] * 18
        assert report["ready"] == 18 and report["failed"] == 0
        redrawn = {(art.key, art.pose): art for art in sessions.written}
        assert len(redrawn) == 18 and all(art.status == "ready" for art in redrawn.values())
        # What was written, over what was there: the next plan is empty.
        after = [r for r in rows if (r.key, r.pose) not in redrawn] + list(redrawn.values())
        assert svc.plan_art(CAST_2696 + PLACES_2696, after, now=NOW) == []
