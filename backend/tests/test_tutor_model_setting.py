"""The tutor model settings expose a dropdown and validate the choice (#2483).

``tutor-model`` and ``tutor-suggestions-model`` gained ``allowed_options`` so the
admin UI renders a `<select>` and the backend rejects an out-of-list value,
mirroring ``ai-model-content``.
"""

from __future__ import annotations

import pytest

from app.domain.services.platform_settings_service import _validate_value
from app.infrastructure.config.platform_defaults import DEFAULTS_BY_KEY


@pytest.mark.parametrize("key", ["tutor-model", "tutor-suggestions-model"])
def test_tutor_model_settings_are_dropdowns(key):
    defn = DEFAULTS_BY_KEY[key]
    assert defn.allowed_options, f"{key} should expose allowed_options for a dropdown"
    # Default must itself be a valid option.
    assert defn.default in defn.allowed_options
    # A Moonshot model is offered so the tutor can run non-Anthropic.
    assert "moonshot-v1-128k" in defn.allowed_options


@pytest.mark.parametrize("key", ["tutor-model", "tutor-suggestions-model"])
def test_tutor_model_rejects_value_outside_allowed_options(key):
    defn = DEFAULTS_BY_KEY[key]
    with pytest.raises(ValueError, match="must be one of"):
        _validate_value(defn, "gpt-4o-not-allowed")


@pytest.mark.parametrize("key", ["tutor-model", "tutor-suggestions-model"])
def test_tutor_model_accepts_allowed_value(key):
    defn = DEFAULTS_BY_KEY[key]
    assert _validate_value(defn, "moonshot-v1-128k") == "moonshot-v1-128k"
