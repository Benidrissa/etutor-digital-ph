"""Country code canonicalization.

Historically ``user.country`` and inbound ``country`` query params have been
stored/sent in two different encodings:

* ISO 3166-1 alpha-2 codes (``BF``, ``CI``) — what the AI prompt maps and the
  ``generated_content.country_context`` cache key use.
* Onboarding slugs (``burkina-faso``, ``cote-divoire``) — produced by an older
  onboarding form (the shared ``frontend/lib/countries.ts`` now stores ISO
  codes, but legacy profiles still hold slugs).

When the two mix, the exact-country cache lookup never matches, so learners get
cross-country fallback content and the backfill task regenerates the same lesson
once per encoding. ``canonicalize_country`` collapses every known form to the
ISO code so cache lookups, the fallback query, and background regeneration all
key on one value.
"""

from __future__ import annotations

# ISO alpha-2 → onboarding slug (mirrors frontend/lib/countries.ts `key`).
_ISO_TO_SLUG = {
    "BJ": "benin",
    "BF": "burkina-faso",
    "CV": "cabo-verde",
    "CI": "cote-divoire",
    "GM": "gambia",
    "GH": "ghana",
    "GN": "guinea",
    "GW": "guinea-bissau",
    "LR": "liberia",
    "ML": "mali",
    "NE": "niger",
    "NG": "nigeria",
    "SN": "senegal",
    "SL": "sierra-leone",
    "TG": "togo",
    "OWA": "other-west-african",
    "OTH": "other",
}

_VALID_ISO = frozenset(_ISO_TO_SLUG)

# Every non-ISO spelling → ISO. Includes onboarding slugs plus a few common
# display-name forms so the canonicalizer is forgiving of legacy data.
_ALIAS_TO_ISO = {slug: iso for iso, slug in _ISO_TO_SLUG.items()}
_ALIAS_TO_ISO.update(
    {
        # display names (fr/en), lower-cased and apostrophe-normalized
        "burkina faso": "BF",
        "cote d'ivoire": "CI",
        "cote divoire": "CI",
        "côte d'ivoire": "CI",
        "senegal": "SN",
        "sénégal": "SN",
        "cabo verde": "CV",
        "cape verde": "CV",
        "cap-vert": "CV",
        "guinea-bissau": "GW",
        "guinée-bissau": "GW",
        "sierra leone": "SL",
    }
)

DEFAULT_COUNTRY = "CI"


def canonicalize_country(value: str | None, default: str = DEFAULT_COUNTRY) -> str:
    """Return the ISO alpha-2 code for ``value``.

    - ``None``/blank → ``default``.
    - A valid ISO code (any case) is passed through upper-cased.
    - A known slug or display name is mapped to its ISO code.
    - Anything unrecognized is returned upper-cased and trimmed (so an unknown
      but ISO-shaped value still round-trips) rather than silently coerced to
      the default, which would mask real data issues.
    """
    if not value or not value.strip():
        return default
    raw = value.strip()
    upper = raw.upper()
    if upper in _VALID_ISO:
        return upper
    alias = _ALIAS_TO_ISO.get(raw.lower())
    if alias:
        return alias
    return upper
