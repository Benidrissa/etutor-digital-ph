"""Tests for classify_provider_error (#2571).

Pure unit tests — no DB, no network. The quota case uses the exact error
message observed on staging when the Moonshot account was suspended for
insufficient balance (surfaced as an opaque 502 before #2571).
"""

from app.ai.providers import ProviderErrorKind, classify_provider_error


class FakeAPIStatusError(Exception):
    """Mimics anthropic/openai APIStatusError: message text + status_code."""

    def __init__(self, message: str, status_code: int) -> None:
        super().__init__(message)
        self.status_code = status_code


MOONSHOT_SUSPENDED_429 = (
    "Error code: 429 - {'error': {'message': 'Your account "
    "org-a798fb7c8bc3471e8009860705b0abf7 <ak-***> is suspended due to "
    "insufficient balance, please recharge your account or check your plan "
    "and billing details', 'type': 'exceeded_current_quota_error'}}"
)


def test_moonshot_suspended_balance_is_quota():
    exc = FakeAPIStatusError(MOONSHOT_SUSPENDED_429, status_code=429)
    assert classify_provider_error(exc) is ProviderErrorKind.QUOTA


def test_openai_insufficient_quota_is_quota():
    exc = FakeAPIStatusError(
        "Error code: 429 - {'error': {'type': 'insufficient_quota', "
        "'message': 'You exceeded your current quota, please check your plan "
        "and billing details.'}}",
        status_code=429,
    )
    assert classify_provider_error(exc) is ProviderErrorKind.QUOTA


def test_anthropic_low_credit_is_quota():
    exc = FakeAPIStatusError(
        "Error code: 400 - {'error': {'type': 'invalid_request_error', 'message': "
        "'Your credit balance is too low to access the Anthropic API.'}}",
        status_code=400,
    )
    assert classify_provider_error(exc) is ProviderErrorKind.QUOTA


def test_plain_rate_limit_429_is_unknown():
    # A transient rate limit carries no billing marker — must NOT be
    # reported as a quota/billing problem.
    exc = FakeAPIStatusError("Error code: 429 - rate limit exceeded", status_code=429)
    assert classify_provider_error(exc) is ProviderErrorKind.UNKNOWN


def test_invalid_api_key_401_is_auth():
    exc = FakeAPIStatusError(
        "Error code: 401 - {'error': {'code': 'invalid_api_key'}}", status_code=401
    )
    assert classify_provider_error(exc) is ProviderErrorKind.AUTH


def test_forbidden_403_is_auth():
    exc = FakeAPIStatusError("Error code: 403 - permission denied", status_code=403)
    assert classify_provider_error(exc) is ProviderErrorKind.AUTH


def test_auth_marker_without_status_code_is_auth():
    assert classify_provider_error(Exception("authentication_error: bad key")) is (
        ProviderErrorKind.AUTH
    )


def test_generic_exception_is_unknown():
    assert classify_provider_error(RuntimeError("connection reset")) is ProviderErrorKind.UNKNOWN


def test_server_error_500_is_unknown():
    exc = FakeAPIStatusError("Error code: 500 - internal error", status_code=500)
    assert classify_provider_error(exc) is ProviderErrorKind.UNKNOWN
