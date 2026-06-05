"""Provider-agnostic payment contract.

A :class:`PaymentProvider` turns an amount into a hosted-checkout URL and verifies
the asynchronous webhook the provider calls back with. Implementations live next to
this module (``paystack.py``, ``wave.py``, ``orange_money.py``). The API layer and
``SubscriptionService`` only ever see :class:`InitResult` / :class:`PaymentEvent`,
never provider-specific payloads.
"""

from __future__ import annotations

import enum
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


class PaymentProviderName(enum.StrEnum):
    """App-layer provider identifier. Stored as a plain string column — NOT a PG
    enum — so it dodges the conftest PG-ENUM materialization limitation."""

    orange_money = "orange_money"
    wave = "wave"
    paystack = "paystack"


class PaymentProviderError(RuntimeError):
    """Raised when a provider is misconfigured/disabled or its API call fails."""


@dataclass(frozen=True)
class InitResult:
    """Outcome of initializing a hosted checkout."""

    checkout_url: str
    provider_reference: str


@dataclass(frozen=True)
class PaymentEvent:
    """Normalized webhook event. ``status`` is canonicalized to ``success`` |
    ``failed`` | ``pending`` so the API layer never branches on provider wording."""

    reference: str
    amount: int
    currency: str
    status: str
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def is_success(self) -> bool:
        return self.status == "success"


@runtime_checkable
class PaymentProvider(Protocol):
    """Hosted-checkout + webhook contract every provider implements."""

    name: str

    async def initialize_transaction(
        self,
        *,
        amount: int,
        currency: str,
        reference: str,
        email: str | None,
        return_url: str,
        notify_url: str,
        metadata: dict[str, Any] | None = None,
    ) -> InitResult:
        """Create a checkout session and return its hosted URL + provider reference."""
        ...

    def verify_webhook(self, raw_body: bytes, headers: Mapping[str, str]) -> bool:
        """Return True iff the webhook signature is valid for ``raw_body``."""
        ...

    def parse_event(self, payload: dict[str, Any]) -> PaymentEvent | None:
        """Map a verified webhook payload to a :class:`PaymentEvent` (or None to ignore)."""
        ...
