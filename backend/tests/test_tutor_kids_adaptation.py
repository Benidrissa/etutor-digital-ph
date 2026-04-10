"""Unit tests for kids-adaptive AI tutor prompt and multi-domain country context."""

from app.ai.prompts.tutor import (
    TutorContext,
    _get_country_context,
    _get_level_instruction,
    get_socratic_system_prompt,
)


def _make_adult_context(**kwargs) -> TutorContext:
    defaults = dict(
        user_level=2,
        user_language="fr",
        user_country="SN",
        is_kids=False,
    )
    defaults.update(kwargs)
    return TutorContext(**defaults)


def _make_kids_context(**kwargs) -> TutorContext:
    defaults = dict(
        user_level=2,
        user_language="fr",
        user_country="SN",
        is_kids=True,
        age_min=6,
        age_max=12,
    )
    defaults.update(kwargs)
    return TutorContext(**defaults)


class TestTutorContextKidsFields:
    def test_default_is_not_kids(self):
        ctx = TutorContext(user_level=1, user_language="fr", user_country="SN")
        assert ctx.is_kids is False
        assert ctx.age_min is None
        assert ctx.age_max is None

    def test_kids_fields_set(self):
        ctx = TutorContext(
            user_level=1,
            user_language="fr",
            user_country="SN",
            is_kids=True,
            age_min=6,
            age_max=12,
        )
        assert ctx.is_kids is True
        assert ctx.age_min == 6
        assert ctx.age_max == 12


class TestGetLevelInstruction:
    def test_adult_level4_returns_expert(self):
        result = _get_level_instruction(level=4, is_kids=False)
        assert "Expert" in result
        assert "L4" in result

    def test_adult_level4_default_is_not_kids(self):
        result = _get_level_instruction(level=4)
        assert "Expert" in result

    def test_kids_level4_returns_maitre_not_expert(self):
        result = _get_level_instruction(level=4, is_kids=True)
        assert "Ma\u00eetre" in result
        assert "Expert" not in result

    def test_kids_level1_returns_decouverte(self):
        result = _get_level_instruction(level=1, is_kids=True)
        assert "D\u00e9couverte" in result

    def test_kids_level2_returns_explorateur(self):
        result = _get_level_instruction(level=2, is_kids=True)
        assert "Explorateur" in result

    def test_kids_level3_returns_champion(self):
        result = _get_level_instruction(level=3, is_kids=True)
        assert "Champion" in result

    def test_adult_level1_returns_debutant(self):
        result = _get_level_instruction(level=1, is_kids=False)
        assert "D\u00e9butant" in result

    def test_adult_level3_returns_avance(self):
        result = _get_level_instruction(level=3, is_kids=False)
        assert "Avanc\u00e9" in result


class TestGetCountryContext:
    def test_sn_no_domain_returns_health_context(self):
        result = _get_country_context("SN")
        assert "paludisme" in result
        assert "S\u00e9n\u00e9gal" in result

    def test_sn_none_domain_returns_health_context(self):
        result = _get_country_context("SN", course_domain=None)
        assert "paludisme" in result

    def test_sn_health_domain_returns_health_context(self):
        result = _get_country_context("SN", course_domain="Sant\u00e9 publique")
        assert "paludisme" in result

    def test_sn_math_domain_returns_generic_no_disease(self):
        result = _get_country_context("SN", course_domain="Mathematics")
        assert "paludisme" not in result
        assert "S\u00e9n\u00e9gal" in result
        assert "Afrique de l'Ouest" in result

    def test_sn_engineering_domain_returns_generic(self):
        result = _get_country_context("SN", course_domain="Engineering")
        assert "paludisme" not in result

    def test_ml_no_domain_returns_health_context(self):
        result = _get_country_context("ML")
        assert "paludisme" in result or "m\u00e9ningite" in result

    def test_unknown_country_no_domain_returns_west_africa(self):
        result = _get_country_context("XX")
        assert "Afrique de l'Ouest" in result

    def test_sn_tax_domain_returns_generic(self):
        result = _get_country_context("SN", course_domain="Fiscalit\u00e9 et comptabilit\u00e9")
        assert "paludisme" not in result


class TestSocraticPromptKids:
    def test_adult_prompt_contains_tuteur_ia_specialise(self):
        ctx = _make_adult_context()
        prompt = get_socratic_system_prompt(ctx, [])
        assert "tuteur IA sp\u00e9cialis\u00e9" in prompt

    def test_kids_prompt_contains_tuteur_ami(self):
        ctx = _make_kids_context()
        prompt = get_socratic_system_prompt(ctx, [])
        assert "tuteur ami" in prompt.lower() or "tuteur" in prompt.lower()
        assert "tuteur IA sp\u00e9cialis\u00e9" not in prompt

    def test_kids_prompt_contains_encouraging_language(self):
        ctx = _make_kids_context(age_min=6, age_max=10)
        prompt = get_socratic_system_prompt(ctx, [])
        assert "encourageant" in prompt or "jeunes apprenants" in prompt

    def test_adult_prompt_not_kids_keyword(self):
        ctx = _make_adult_context()
        prompt = get_socratic_system_prompt(ctx, [])
        assert "jeunes apprenants" not in prompt

    def test_kids_prompt_has_audience_guidance(self):
        ctx = _make_kids_context(age_min=6, age_max=10)
        prompt = get_socratic_system_prompt(ctx, [])
        assert "PÉDAGOGIE" in prompt or "ADAPTATION" in prompt

    def test_kids_prompt_has_softer_forbidden_rule(self):
        ctx = _make_kids_context()
        prompt = get_socratic_system_prompt(ctx, [])
        assert "Ne r\u00e9ponds JAMAIS directement" not in prompt

    def test_adult_prompt_has_strict_forbidden_rule(self):
        ctx = _make_adult_context()
        prompt = get_socratic_system_prompt(ctx, [])
        assert "Ne r\u00e9ponds JAMAIS directement" in prompt

    def test_kids_level_label_in_prompt(self):
        ctx = _make_kids_context(user_level=4)
        prompt = get_socratic_system_prompt(ctx, [])
        assert "Ma\u00eetre" in prompt
        assert (
            "Expert" not in prompt.split("## CONTEXTE")[1].split("## LANGUE")[0]
            if "## CONTEXTE" in prompt
            else True
        )

    def test_adult_prompt_word_for_word_unchanged_level(self):
        ctx = _make_adult_context(user_level=4)
        prompt = get_socratic_system_prompt(ctx, [])
        assert "Expert (L4)" in prompt

    def test_kids_early_tier_concision_2_3_phrases(self):
        ctx = _make_kids_context(age_min=5, age_max=8)
        prompt = get_socratic_system_prompt(ctx, [])
        assert "2-3 phrases" in prompt

    def test_adult_concision_3_5_phrases(self):
        ctx = _make_adult_context()
        prompt = get_socratic_system_prompt(ctx, [])
        assert "3-5 phrases" in prompt
