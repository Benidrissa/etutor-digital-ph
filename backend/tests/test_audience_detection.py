"""Unit tests for audience detection and age-tier guidance (kids-adaptive prompts)."""

from unittest.mock import MagicMock

from app.ai.prompts.audience import (
    KIDS_AUDIENCE_SLUGS,
    AudienceContext,
    detect_audience,
    detect_audience_from_slugs,
    get_audience_guidance,
)


def _make_taxonomy(slug: str, type_: str = "audience") -> MagicMock:
    tc = MagicMock()
    tc.slug = slug
    tc.type = type_
    return tc


def _make_course(
    taxonomy_slugs: list[tuple[str, str]] | None = None,
    title_en: str = "",
    title_fr: str = "",
) -> MagicMock:
    course = MagicMock()
    course.title_en = title_en
    course.title_fr = title_fr
    cats = [_make_taxonomy(slug, type_) for slug, type_ in (taxonomy_slugs or [])]
    course.taxonomy_categories = cats
    return course


class TestDetectAudienceNone:
    def test_returns_adult_for_none(self):
        result = detect_audience(None)
        assert result.is_kids is False
        assert result.age_min is None
        assert result.age_max is None
        assert result.audience_slugs == []


class TestDetectAudienceAdultCourse:
    def test_professional_taxonomy_returns_adult(self):
        course = _make_course(
            taxonomy_slugs=[("public_health", "domain"), ("professionals", "audience")]
        )
        result = detect_audience(course)
        assert result.is_kids is False

    def test_no_taxonomy_returns_adult(self):
        course = _make_course(taxonomy_slugs=[])
        result = detect_audience(course)
        assert result.is_kids is False

    def test_domain_slug_only_returns_adult(self):
        course = _make_course(taxonomy_slugs=[("epidemiology", "domain")])
        result = detect_audience(course)
        assert result.is_kids is False


class TestDetectAudienceKidsCourse:
    def test_kindergarten_slug_returns_kids(self):
        course = _make_course(taxonomy_slugs=[("kindergarten", "audience")])
        result = detect_audience(course)
        assert result.is_kids is True
        assert "kindergarten" in result.audience_slugs

    def test_primary_school_slug_returns_kids(self):
        course = _make_course(taxonomy_slugs=[("primary_school", "audience")])
        result = detect_audience(course)
        assert result.is_kids is True

    def test_secondary_school_slug_returns_kids(self):
        course = _make_course(taxonomy_slugs=[("secondary_school", "audience")])
        result = detect_audience(course)
        assert result.is_kids is True

    def test_mixed_kids_and_domain_slugs(self):
        course = _make_course(
            taxonomy_slugs=[("primary_school", "audience"), ("mathematics", "domain")]
        )
        result = detect_audience(course)
        assert result.is_kids is True

    def test_all_kids_slugs_in_frozenset(self):
        for slug in KIDS_AUDIENCE_SLUGS:
            course = _make_course(taxonomy_slugs=[(slug, "audience")])
            result = detect_audience(course)
            assert result.is_kids is True, f"Expected is_kids=True for slug '{slug}'"


class TestAgeRangeParsingFromTitle:
    def test_english_parentheses_ages(self):
        course = _make_course(
            taxonomy_slugs=[("primary_school", "audience")],
            title_en="Village Math Mastery (Ages 6-12)",
        )
        result = detect_audience(course)
        assert result.age_min == 6
        assert result.age_max == 12

    def test_english_ages_en_dash(self):
        course = _make_course(
            taxonomy_slugs=[("primary_school", "audience")],
            title_en="Mastering the Marketplace (Ages 6\u201315)",
        )
        result = detect_audience(course)
        assert result.age_min == 6
        assert result.age_max == 15

    def test_french_a_pattern(self):
        course = _make_course(
            taxonomy_slugs=[("primary_school", "audience")],
            title_fr="Maîtriser les marchés (6 à 12 ans)",
        )
        result = detect_audience(course)
        assert result.age_min == 6
        assert result.age_max == 12

    def test_french_hyphen_pattern(self):
        course = _make_course(
            taxonomy_slugs=[("kindergarten", "audience")],
            title_fr="Les formes et couleurs (3-6 ans)",
        )
        result = detect_audience(course)
        assert result.age_min == 3
        assert result.age_max == 6

    def test_age_in_english_title_preferred_over_french(self):
        course = _make_course(
            taxonomy_slugs=[("primary_school", "audience")],
            title_en="Math Mastery (Ages 7-11)",
            title_fr="Maîtrise des maths (3-6 ans)",
        )
        result = detect_audience(course)
        assert result.age_min == 7
        assert result.age_max == 11


class TestAgeRangeFallbackFromSlugs:
    def test_kindergarten_only_fallback(self):
        course = _make_course(taxonomy_slugs=[("kindergarten", "audience")])
        result = detect_audience(course)
        assert result.age_min == 3
        assert result.age_max == 6

    def test_primary_school_only_fallback(self):
        course = _make_course(taxonomy_slugs=[("primary_school", "audience")])
        result = detect_audience(course)
        assert result.age_min == 6
        assert result.age_max == 12

    def test_secondary_school_only_fallback(self):
        course = _make_course(taxonomy_slugs=[("secondary_school", "audience")])
        result = detect_audience(course)
        assert result.age_min == 12
        assert result.age_max == 18

    def test_kindergarten_and_primary_gives_widest_range(self):
        course = _make_course(
            taxonomy_slugs=[("kindergarten", "audience"), ("primary_school", "audience")]
        )
        result = detect_audience(course)
        assert result.age_min == 3
        assert result.age_max == 12


class TestGetAudienceGuidance:
    def test_adult_context_returns_empty_string(self):
        adult = AudienceContext(is_kids=False)
        assert get_audience_guidance(adult, "fr") == ""
        assert get_audience_guidance(adult, "en") == ""

    def test_early_tier_fr(self):
        ctx = AudienceContext(is_kids=True, age_min=5, age_max=7)
        guidance = get_audience_guidance(ctx, "fr")
        assert "5-8 ans" in guidance
        assert "10-15 mots" in guidance

    def test_early_tier_en(self):
        ctx = AudienceContext(is_kids=True, age_min=6, age_max=8)
        guidance = get_audience_guidance(ctx, "en")
        assert "5-8" in guidance
        assert "10-15 words" in guidance

    def test_middle_tier_fr(self):
        ctx = AudienceContext(is_kids=True, age_min=9, age_max=12)
        guidance = get_audience_guidance(ctx, "fr")
        assert "9-12 ans" in guidance

    def test_middle_tier_en(self):
        ctx = AudienceContext(is_kids=True, age_min=9, age_max=12)
        guidance = get_audience_guidance(ctx, "en")
        assert "9-12" in guidance

    def test_teen_tier_fr(self):
        ctx = AudienceContext(is_kids=True, age_min=13, age_max=15)
        guidance = get_audience_guidance(ctx, "fr")
        assert "13-15 ans" in guidance

    def test_teen_tier_en(self):
        ctx = AudienceContext(is_kids=True, age_min=13, age_max=15)
        guidance = get_audience_guidance(ctx, "en")
        assert "13-15" in guidance

    def test_ages_6_12_give_middle_tier(self):
        ctx = AudienceContext(is_kids=True, age_min=6, age_max=12)
        guidance_fr = get_audience_guidance(ctx, "fr")
        assert "9-12 ans" in guidance_fr

    def test_ages_6_15_give_teen_tier(self):
        ctx = AudienceContext(is_kids=True, age_min=6, age_max=15)
        guidance_fr = get_audience_guidance(ctx, "fr")
        assert "13-15 ans" in guidance_fr


class TestDetectAudienceFromSlugs:
    def test_none_returns_adult(self):
        result = detect_audience_from_slugs(None)
        assert result.is_kids is False

    def test_empty_list_returns_adult(self):
        result = detect_audience_from_slugs([])
        assert result.is_kids is False

    def test_adult_slugs_returns_adult(self):
        result = detect_audience_from_slugs(["professionals", "public_health"])
        assert result.is_kids is False

    def test_primary_school_slug_returns_kids(self):
        result = detect_audience_from_slugs(["primary_school"])
        assert result.is_kids is True
        assert "primary_school" in result.audience_slugs

    def test_kindergarten_slug_returns_kids(self):
        result = detect_audience_from_slugs(["kindergarten"])
        assert result.is_kids is True
        assert result.age_min == 3
        assert result.age_max == 6

    def test_secondary_school_slug_returns_kids(self):
        result = detect_audience_from_slugs(["secondary_school"])
        assert result.is_kids is True

    def test_mixed_slugs_with_kids(self):
        result = detect_audience_from_slugs(["primary_school", "mathematics"])
        assert result.is_kids is True

    def test_age_extracted_from_title_en(self):
        result = detect_audience_from_slugs(
            ["primary_school"],
            title_en="Village Math Mastery (Ages 6-12)",
        )
        assert result.is_kids is True
        assert result.age_min == 6
        assert result.age_max == 12

    def test_age_extracted_from_title_fr(self):
        result = detect_audience_from_slugs(
            ["primary_school"],
            title_fr="Maîtriser les marchés (6 à 12 ans)",
        )
        assert result.is_kids is True
        assert result.age_min == 6
        assert result.age_max == 12

    def test_title_en_preferred_over_title_fr(self):
        result = detect_audience_from_slugs(
            ["primary_school"],
            title_en="Math Mastery (Ages 7-11)",
            title_fr="Maîtrise des maths (3-6 ans)",
        )
        assert result.age_min == 7
        assert result.age_max == 11

    def test_slug_fallback_when_no_title_age(self):
        result = detect_audience_from_slugs(
            ["primary_school"],
            title_en="Math Mastery",
        )
        assert result.age_min == 6
        assert result.age_max == 12


class TestSyllabusPromptRouting:
    def test_adult_prompt_does_not_use_andragogy_override(self):
        from app.domain.services.course_agent_service import CourseAgentService

        svc = CourseAgentService()
        prompt = svc._build_prompt(
            title_fr="Épidémiologie",
            title_en="Epidemiology",
            domains_str="Public Health",
            levels_str="intermediate",
            audience_str="Professionals",
            estimated_hours=40,
            resource_block="",
            audience_type=["professionals"],
        )
        assert "andragogy" in prompt
        assert "Piaget" not in prompt
        assert "play-based" not in prompt

    def test_kids_prompt_uses_child_pedagogy(self):
        from app.domain.services.course_agent_service import CourseAgentService

        svc = CourseAgentService()
        prompt = svc._build_prompt(
            title_fr="Maths au Village (6-12 ans)",
            title_en="Village Math (Ages 6-12)",
            domains_str="Mathematics",
            levels_str="beginner",
            audience_str="primary_school",
            estimated_hours=20,
            resource_block="",
            audience_type=["primary_school"],
        )
        assert "andragogy" not in prompt
        assert "Piaget" in prompt
        assert "play-based" in prompt
        assert "60% pass" in prompt
        assert "10-20 bilingual cards" in prompt

    def test_no_audience_type_produces_adult_prompt(self):
        from app.domain.services.course_agent_service import CourseAgentService

        svc = CourseAgentService()
        prompt = svc._build_prompt(
            title_fr="Santé publique",
            title_en="Public Health",
            domains_str="Health",
            levels_str="all",
            audience_str="General",
            estimated_hours=30,
            resource_block="",
            audience_type=None,
        )
        assert "andragogy" in prompt

    def test_get_admin_prompt_selects_kids_key_for_kids_audience(self):
        from unittest.mock import MagicMock, patch

        from app.domain.services.course_agent_service import CourseAgentService

        svc = CourseAgentService()
        mock_defn = MagicMock()
        mock_defn.default = "default_value"

        with (
            patch(
                "app.domain.services.course_agent_service.CourseAgentService._get_admin_prompt",
                wraps=svc._get_admin_prompt,
            ),
            patch("app.domain.services.platform_settings_service.SettingsCache") as mock_cache_cls,
            patch(
                "app.infrastructure.config.platform_defaults.DEFAULTS_BY_KEY",
                {
                    "ai-prompt-syllabus-kids-system": mock_defn,
                    "ai-prompt-syllabus-system": mock_defn,
                },
            ),
        ):
            mock_cache = MagicMock()
            mock_cache.get.return_value = "customized kids prompt for {age_range}"
            mock_cache_cls.instance.return_value = mock_cache

            result = svc._get_admin_prompt(
                audience_type=["primary_school"],
                course_title="Test",
                course_domain="Math",
                level="beginner",
                estimated_hours="20",
                resource_text="",
                age_range="6-12",
                audience_guidance="",
            )
            mock_cache.get.assert_called_once_with("ai-prompt-syllabus-kids-system")
            assert result == "customized kids prompt for 6-12"

    def test_get_admin_prompt_selects_adult_key_for_adult_audience(self):
        from unittest.mock import MagicMock, patch

        from app.domain.services.course_agent_service import CourseAgentService

        svc = CourseAgentService()
        mock_defn = MagicMock()
        mock_defn.default = "default_value"

        with (
            patch("app.domain.services.platform_settings_service.SettingsCache") as mock_cache_cls,
            patch(
                "app.infrastructure.config.platform_defaults.DEFAULTS_BY_KEY",
                {
                    "ai-prompt-syllabus-kids-system": mock_defn,
                    "ai-prompt-syllabus-system": mock_defn,
                },
            ),
        ):
            mock_cache = MagicMock()
            mock_cache.get.return_value = "customized adult prompt"
            mock_cache_cls.instance.return_value = mock_cache

            result = svc._get_admin_prompt(
                audience_type=["professionals"],
                course_title="Test",
                course_domain="Health",
                level="advanced",
                estimated_hours="40",
                resource_text="",
                age_range="",
                audience_guidance="",
            )
            mock_cache.get.assert_called_once_with("ai-prompt-syllabus-system")
            assert result == "customized adult prompt"
