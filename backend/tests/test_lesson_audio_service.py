"""Unit tests for LessonAudioService — script generation and prompt building."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.domain.services.lesson_audio_service import (
    LessonAudioService,
    _build_lesson_audio_system_prompt,
    _estimate_duration,
)


class TestBuildLessonAudioSystemPrompt:
    def test_french_prompt_mentions_french(self):
        prompt = _build_lesson_audio_system_prompt("fr")
        assert "French" in prompt

    def test_english_prompt_mentions_english(self):
        prompt = _build_lesson_audio_system_prompt("en")
        assert "English" in prompt

    def test_prompt_mentions_500_words(self):
        prompt = _build_lesson_audio_system_prompt("en")
        assert "500 words" in prompt

    def test_prompt_mentions_west_africa(self):
        prompt = _build_lesson_audio_system_prompt("fr")
        assert "West Africa" in prompt

    def test_prompt_no_markdown(self):
        prompt = _build_lesson_audio_system_prompt("en")
        assert "DO NOT include headers" in prompt

    def test_prompt_output_instruction(self):
        prompt = _build_lesson_audio_system_prompt("en")
        assert "Output only the script text" in prompt


class TestEstimateDuration:
    def test_minimum_duration_is_one(self):
        assert _estimate_duration(0) == 1

    def test_ogg_opus_estimate(self):
        # OGG Opus speech ~6 KB/s = 6144 bytes/sec
        # 1 minute = 368640 bytes
        duration = _estimate_duration(368640)
        assert 55 <= duration <= 65

    def test_small_file(self):
        duration = _estimate_duration(6144)
        assert duration == 1


class TestGenerateScript:
    @pytest.fixture
    def mock_claude(self):
        service = AsyncMock()
        response = MagicMock()
        block = MagicMock()
        block.text = "This is the lesson audio script."
        response.content = [block]
        service.generate_lesson_content = AsyncMock(return_value=response)
        return service

    @pytest.fixture
    def audio_service(self, mock_claude):
        return LessonAudioService(claude_service=mock_claude)

    async def test_generate_script_returns_text(self, audio_service):
        result = await audio_service._generate_script(
            "Some lesson content about epidemiology.", "en"
        )
        assert result == "This is the lesson audio script."

    async def test_generate_script_passes_content_to_claude(self, audio_service, mock_claude):
        await audio_service._generate_script("Lesson about DHIS2.", "fr")
        call_args = mock_claude.generate_lesson_content.call_args
        user_message = call_args.kwargs["user_message"]
        assert "Lesson about DHIS2." in user_message

    async def test_generate_script_uses_correct_language_prompt(self, audio_service, mock_claude):
        await audio_service._generate_script("Content.", "fr")
        call_args = mock_claude.generate_lesson_content.call_args
        system_prompt = call_args.kwargs["system_prompt"]
        assert "French" in system_prompt

    async def test_generate_script_raises_on_empty_response(self, mock_claude):
        response = MagicMock()
        block = MagicMock()
        block.text = "   "
        response.content = [block]
        mock_claude.generate_lesson_content = AsyncMock(return_value=response)
        service = LessonAudioService(claude_service=mock_claude)

        with pytest.raises(ValueError, match="empty script"):
            await service._generate_script("Some content.", "en")

    async def test_generate_script_truncates_long_content(self, audio_service, mock_claude):
        long_content = "x" * 10000
        await audio_service._generate_script(long_content, "en")
        call_args = mock_claude.generate_lesson_content.call_args
        user_message = call_args.kwargs["user_message"]
        # Should be truncated to 4000 chars
        assert len(user_message) < 5000
