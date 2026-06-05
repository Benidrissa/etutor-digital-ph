"""Construct payment providers from platform settings.

Credentials and enable-flags live in ``platform_defaults.py`` (``payments``
category) and are read through the in-process :class:`SettingsCache`, so admins
can rotate keys from the settings UI without a redeploy.
"""

from __future__ import annotations

from app.domain.services.platform_settings_service import SettingsCache
from app.integrations.payments.base import PaymentProvider, PaymentProviderError
from app.integrations.payments.orange_money import OrangeMoneyProvider
from app.integrations.payments.paystack import PaystackProvider
from app.integrations.payments.wave import WaveProvider

PROVIDER_NAMES = ("orange_money", "wave", "paystack")

# Setting key that toggles each provider in the checkout selector.
_ENABLED_KEYS = {
    "orange_money": "payments-orange-money-enabled",
    "wave": "payments-wave-enabled",
    "paystack": "payments-paystack-enabled",
}


def is_enabled(name: str) -> bool:
    sc = SettingsCache.instance()
    return bool(sc.get(_ENABLED_KEYS.get(name, ""), False))


def enabled_providers() -> list[str]:
    """Names of providers an admin has switched on — drives the frontend selector."""
    return [name for name in PROVIDER_NAMES if is_enabled(name)]


def get_provider(name: str) -> PaymentProvider:
    """Build a configured provider, or raise if unknown/disabled/unconfigured."""
    if name not in PROVIDER_NAMES:
        raise PaymentProviderError(f"Unknown payment provider '{name}'")
    if not is_enabled(name):
        raise PaymentProviderError(f"Payment provider '{name}' is disabled")

    sc = SettingsCache.instance()
    if name == "paystack":
        return PaystackProvider(secret_key=sc.get("payments-paystack-secret-key", ""))
    if name == "wave":
        return WaveProvider(
            api_key=sc.get("payments-wave-api-key", ""),
            webhook_secret=sc.get("payments-wave-webhook-secret", ""),
        )
    return OrangeMoneyProvider(
        client_id=sc.get("payments-orange-client-id", ""),
        client_secret=sc.get("payments-orange-client-secret", ""),
        merchant_key=sc.get("payments-orange-merchant-key", ""),
        country=sc.get("payments-orange-country", "civ"),
    )


def provider_currency(name: str) -> str:
    """Settlement currency for a provider (Paystack is multi-currency; OM/Wave are XOF)."""
    if name == "paystack":
        return SettingsCache.instance().get("payments-paystack-currency", "XOF")
    return "XOF"
