"""Provider-agnostic payment integrations (Orange Money, Wave, Paystack).

Each provider exposes the :class:`PaymentProvider` protocol from ``base``: hosted
checkout initialization + HMAC-verified webhook parsing. The unified
``/api/v1/payments`` router and ``SubscriptionService.confirm_payment`` consume
these — no provider-specific branching leaks into the API layer.
"""

from app.integrations.payments.base import (
    InitResult,
    PaymentEvent,
    PaymentProvider,
    PaymentProviderError,
)
from app.integrations.payments.registry import (
    PROVIDER_NAMES,
    enabled_providers,
    get_provider,
)

__all__ = [
    "InitResult",
    "PaymentEvent",
    "PaymentProvider",
    "PaymentProviderError",
    "PROVIDER_NAMES",
    "enabled_providers",
    "get_provider",
]
