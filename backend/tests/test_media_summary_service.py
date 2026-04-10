"""Unit tests for media_summary_service — _build_audio_system_prompt and _generate_script."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.domain.services.media_summary_service import (
    MediaSummaryService,
    _build_audio_system_prompt,
)


class TestBuildAudioSystemPrompt:
    def test_no_params_produces_generic_adult_prompt(self):
        prompt = _build_audio_system_prompt(language="en")
        assert "public health" in prompt
        assert "professionals in public health" in prompt
        assert "young learners" not in prompt

    def test_adult_math_course_says_mathematics_not_public_health(self):
        prompt = _build_audio_system_prompt(language="en", course_title="Mathematics")
        assert "Mathematics" in prompt
        assert "public health" not in prompt

    def test_adult_it_course_says_it(self):
        prompt = _build_audio_system_prompt(language="en", course_title="Information Technology")
        assert "Information Technology" in prompt
        assert "public health" not in prompt

    def test_kids_prompt_uses_age_appropriate_style(self):
        prompt = _build_audio_system_prompt(
            language="en",
            course_title="Village Math",
            is_kids=True,
            age_range="6-12",
        )
        assert "children aged 6-12" in prompt
        assert "fun" in prompt
        assert "professionals" not in prompt

    def test_kids_prompt_includes_children_relate_examples(self):
        prompt = _build_audio_system_prompt(
            language="en",
            course_title="Primary Science",
            is_kids=True,
            age_range="6-12",
        )
        assert "children can relate to" in prompt

    def test_adult_prompt_mentions_health_systems(self):
        prompt = _build_audio_system_prompt(language="en")
        assert "health systems" in prompt

    def test_kids_prompt_does_not_mention_health_systems(self):
        prompt = _build_audio_system_prompt(
            language="en",
            course_title="Village Math",
            is_kids=True,
            age_range="6-12",
        )
        assert "health systems" not in prompt

    def test_language_appears_in_prompt(self):
        prompt_fr = _build_audio_system_prompt(language="fr")
        assert "fr" in prompt_fr

        prompt_en = _build_audio_system_prompt(language="en")
        assert "en" in prompt_en

    def test_output_format_instructions_always_present(self):
        for is_kids in [True, False]:
            prompt = _build_audio_system_prompt(
                language="en",
                course_title="Test Course",
                is_kids=is_kids,
                age_range="6-12" if is_kids else "",
            )
            assert "Output only the script text" in prompt
            assert "DO NOT include headers" in prompt
            assert "key takeaways" in prompt

    def test_adult_no_course_title_falls_back_to_public_health(self):
        prompt = _build_audio_system_prompt(language="fr", course_title=None, is_kids=False)
        assert "public health" in prompt


class TestGenerateScriptUsesAudiencePrompt:
    @pytest.fixture
    def mock_claude(self):
        service = AsyncMock()
        response = MagicMock()
        block = MagicMock()
        block.text = "This is the audio script content."
        response.content = [block]
        service.generate_lesson_content = AsyncMock(return_value=response)
        return service

    @pytest.fixture
    def media_service(self, mock_claude):
        return MediaSummaryService(claude_service=mock_claude)

    async def test_generate_script_adult_course_passes_course_title(
        self, media_service, mock_claude
    ):
        await media_service._generate_script(
            module_title="Module 1",
            language="en",
            level=2,
            unit_titles=["Unit A"],
            rag_chunks=[],
            course_title="Tax Policy",
            is_kids=False,
            age_range="",
        )
        call_args = mock_claude.generate_lesson_content.call_args
        system_prompt = call_args.kwargs["system_prompt"]
        assert "Tax Policy" in system_prompt
        assert "public health" not in system_prompt

    async def test_generate_script_kids_course_uses_kids_prompt(self, media_service, mock_claude):
        await media_service._generate_script(
            module_title="Village Math Module 1",
            language="en",
            level=1,
            unit_titles=["Numbers"],
            rag_chunks=[],
            course_title="Village Math",
            is_kids=True,
            age_range="6-12",
        )
        call_args = mock_claude.generate_lesson_content.call_args
        system_prompt = call_args.kwargs["system_prompt"]
        assert "children aged 6-12" in system_prompt
        assert "professionals" not in system_prompt

    async def test_generate_script_no_course_falls_back_to_generic(
        self, media_service, mock_claude
    ):
        await media_service._generate_script(
            module_title="Module 1",
            language="en",
            level=1,
            unit_titles=[],
            rag_chunks=[],
        )
        call_args = mock_claude.generate_lesson_content.call_args
        system_prompt = call_args.kwargs["system_prompt"]
        assert "public health" in system_prompt
        assert "young learners" not in system_prompt

    async def test_generate_script_raises_on_empty_response(self, mock_claude):
        response = MagicMock()
        block = MagicMock()
        block.text = "   "
        response.content = [block]
        mock_claude.generate_lesson_content = AsyncMock(return_value=response)
        service = MediaSummaryService(claude_service=mock_claude)

        with pytest.raises(ValueError, match="empty script"):
            await service._generate_script(
                module_title="Module 1",
                language="fr",
                level=1,
                unit_titles=[],
                rag_chunks=[],
            )
