"""Tests for country code canonicalization (#2581).

Legacy profiles and older onboarding stored country slugs (``burkina-faso``)
while the AI prompt maps and ``generated_content.country_context`` cache key use
ISO codes (``BF``). When the two mix, the exact-country cache lookup never
matches and learners get cross-country fallback content. ``canonicalize_country``
collapses every known form to the ISO code.
"""

from __future__ import annotations

import pytest

from app.domain.services.country_utils import canonicalize_country


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        # onboarding slugs → ISO
        ("burkina-faso", "BF"),
        ("cote-divoire", "CI"),
        ("guinea-bissau", "GW"),
        ("other-west-african", "OWA"),
        # ISO codes pass through (any case)
        ("BF", "BF"),
        ("ci", "CI"),
        ("Ci", "CI"),
        # display names (fr/en) → ISO
        ("Burkina Faso", "BF"),
        ("Côte d'Ivoire", "CI"),
        ("cote d'ivoire", "CI"),
        ("Sénégal", "SN"),
        # whitespace tolerated
        ("  burkina-faso  ", "BF"),
    ],
)
def test_canonicalize_known_forms(value: str, expected: str):
    assert canonicalize_country(value) == expected


@pytest.mark.parametrize("blank", [None, "", "   "])
def test_blank_falls_back_to_default(blank):
    assert canonicalize_country(blank) == "CI"
    assert canonicalize_country(blank, default="SN") == "SN"


def test_unknown_value_is_uppercased_not_defaulted():
    # An unrecognized but ISO-shaped value round-trips upper-cased rather than
    # being silently coerced to the default, so real data issues stay visible.
    assert canonicalize_country("zz") == "ZZ"
    assert canonicalize_country("Atlantis") == "ATLANTIS"


def test_slug_and_iso_map_to_the_same_key():
    # The core bug: these two encodings must collapse to one cache key.
    assert canonicalize_country("burkina-faso") == canonicalize_country("BF")
    assert canonicalize_country("cote-divoire") == canonicalize_country("ci")
