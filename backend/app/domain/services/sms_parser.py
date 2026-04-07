"""SMS body parsers for mobile money payment extraction."""

from __future__ import annotations

import re
from dataclasses import dataclass

ORANGE_MONEY_PATTERN = re.compile(
    r"[Vv]ous\s+avez\s+re[cç]u\s+([\d\s.,]+)\s*FCFA"
    r"\s+du\s+(\d{8,15})",
    re.IGNORECASE,
)
TRANS_ID_PATTERN = re.compile(r"Trans\s+ID:\s*(\S+)", re.IGNORECASE)


@dataclass(frozen=True)
class ParsedPayment:
    amount: int
    phone_number: str
    reference: str
    provider: str


class SmsParser:
    """Registry of provider-specific SMS parsers."""

    def parse(self, body: str, sender: str, fallback_ref: str = "") -> ParsedPayment | None:
        """Try each parser in order. Return first match."""
        for parser in [self._parse_orange_money]:
            result = parser(body, sender, fallback_ref)
            if result is not None:
                return result
        return None

    @staticmethod
    def _parse_orange_money(body: str, sender: str, fallback_ref: str) -> ParsedPayment | None:
        m = ORANGE_MONEY_PATTERN.search(body)
        if m is None:
            return None

        amount = _normalize_amount(m.group(1))
        phone = _normalize_phone(m.group(2))

        tid = TRANS_ID_PATTERN.search(body)
        reference = tid.group(1).rstrip(".") if tid else fallback_ref

        return ParsedPayment(
            amount=amount,
            phone_number=phone,
            reference=reference,
            provider="orange_money",
        )


def _normalize_amount(raw: str) -> int:
    """Convert '65,000.00' or '65 000' to 65000."""
    cleaned = raw.strip()
    # Remove spaces
    cleaned = cleaned.replace(" ", "")
    # Determine if comma or period is decimal separator
    # '65,000.00' -> comma=thousands, period=decimal
    # '65.000,00' -> period=thousands, comma=decimal
    last_comma = cleaned.rfind(",")
    last_period = cleaned.rfind(".")
    if last_comma > last_period:
        # comma is decimal: 65.000,00
        cleaned = cleaned.replace(".", "")
        cleaned = cleaned.replace(",", ".")
    else:
        # period is decimal or no decimal: 65,000.00
        cleaned = cleaned.replace(",", "")
    # Take integer part only (FCFA is whole numbers)
    return int(float(cleaned))


_ECOWAS_COUNTRY_CODES = (
    "224",
    "221",
    "223",
    "225",
    "226",
    "227",
    "228",
    "229",
    "231",
    "233",
    "234",
)


def normalize_phone(raw: str) -> str:
    """Strip country code prefix to get local number (public utility).

    Handles:
    - +22670220689  -> 70220689
    - 0022670220689 -> 70220689
    - 70220689      -> 70220689 (unchanged)
    - 070220689     -> 70220689 (leading 0 stripped if >8 digits remain)
    """
    phone = raw.strip()
    if phone.startswith("+"):
        phone = phone[1:]
        for prefix in _ECOWAS_COUNTRY_CODES:
            if phone.startswith(prefix) and len(phone) > 8:
                phone = phone[len(prefix) :]
                break
    elif phone.startswith("00"):
        phone = phone[2:]
        for prefix in _ECOWAS_COUNTRY_CODES:
            if phone.startswith(prefix) and len(phone) > 8:
                phone = phone[len(prefix) :]
                break
    elif phone.startswith("0") and len(phone) > 8:
        phone = phone[1:]
    return phone


def _normalize_phone(raw: str) -> str:
    """Strip country code prefix to get local number (internal alias)."""
    return normalize_phone(raw)
