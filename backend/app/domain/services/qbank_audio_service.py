"""Question audio generation — French (OpenAI TTS) + Moore/Dioula/Bambara (MMS).

Each qbank question gets an OGG/Opus audio clip per language it supports.
French uses the same OpenAI gpt-4o-mini-tts path as LessonAudioService so
audio quality and file size stay consistent. Moore / Dioula / Bambara go
through the MMS sidecar (see app.integrations.mms_tts).

The audio script is the question read aloud followed by its options, so the
learner can take a test with eyes on the image while the text is read to
them. File size target is ~50 KB per 30s clip (Opus @ 24 kbps).
"""

from __future__ import annotations

import re
import uuid
from typing import Literal

import structlog
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models.question_bank import (
    QBankAudioSource,
    QBankAudioStatus,
    QBankQuestion,
    QBankQuestionAudio,
    QBankQuestionTranslation,
    QuestionBank,
)
from app.infrastructure.config.settings import settings
from app.infrastructure.storage.s3 import S3StorageService
from app.integrations.mms_tts import MMSTTSClient, MMSTTSError
from app.integrations.nllb_translate import NLLBTranslateError

logger = structlog.get_logger(__name__)

SupportedLanguage = Literal["fr", "mos", "dyu", "bam", "ful"]

# Canonical list of languages audio is generated for. Pregeneration loops
# over this tuple when a bank is published so every (question, language)
# pair has a ready clip by the time a learner starts a test (#1674).
SUPPORTED_LANGUAGES: tuple[str, ...] = ("fr", "mos", "dyu", "bam", "ful")

OPUS_CONTENT_TYPE = "audio/ogg"
OPUS_BYTES_PER_SECOND = 6 * 1024  # matches LessonAudioService._estimate_duration


_MMS_PUNCT_RE = re.compile(r"[^\w\s'\-]+", flags=re.UNICODE)
_MMS_SPACES_RE = re.compile(r"\s+")

# Ordinal words for MMS option labels. Saying "a", "b", "c", "d" via MMS
# produces either silence (single letters are not a pronounceable token
# sequence) or a sound too subtle to distinguish options apart. Users
# reported "no difference among options" on #1719. Replace letters with
# native-language ordinal words MMS can pronounce clearly. French path
# is untouched — OpenAI TTS handles "Option A/B/C" natively.
# Sources: standard orthography from the MMS training corpora (vocab.json).
# Fallback to number word if we somehow see a 5+ option question.
_MMS_OPTION_ORDINALS: dict[str, tuple[str, ...]] = {
    # Mooré (mos): numbers / ordinals
    "mos": ("pipi", "yiibu", "tãabo", "naase", "nu"),
    # Dioula (dyu): cardinal numbers used for ordering
    "dyu": ("kelen", "fila", "saba", "naani", "duuru"),
    # Bambara (bam): same root as Dioula
    "bam": ("kelen", "fila", "saba", "naani", "duuru"),
    # Fulfulde (ful)
    "ful": ("goo", "ɗiɗi", "tati", "nayi", "jowi"),
}
# Silence between sentence segments when we splice per-sentence synth
# (#1719 follow-up). 300 ms reads as a natural pause without being
# perceived as a dropout.
_SEGMENT_SILENCE_MS = 300
# Split the script into sentences on the original punctuation BEFORE we
# strip it for the MMS tokenizer. These are the natural boundaries where
# we want the spliced silence to land.
_SENTENCE_SPLIT_RE = re.compile(r"[.!?;]+\s*|\n+")


def _normalize_for_mms(text: str) -> str:
    """Strip characters the Meta MMS VITS tokenizer can't encode (#1719).

    facebook/mms-tts-{mos,dyu,bam,ful} have 32-token character vocabs:
    lowercase letters, a few language-specific diacritics (ɛ, ɔ, ɲ, ŋ,
    ɓ, ɗ, ʋ, ã, ẽ, ĩ, õ, ũ…), plus ``'``, ``-``, space. Anything else —
    including ``? . , : ; !`` and uppercase — becomes an ``<unk>`` token
    that the model renders as noise or silence. VITS learns prosody from
    the ``add_blank`` pad tokens the tokenizer interleaves between
    characters, so stripping punctuation doesn't hurt intelligibility.

    This normalization replaces every non-word, non-hyphen, non-apostrophe
    character with a single space and collapses repeats. Uppercase is
    handled by the tokenizer itself (``normalize_text`` lowercases), but
    we do it here too for clarity in logs.
    """
    lowered = (text or "").lower()
    squashed = _MMS_PUNCT_RE.sub(" ", lowered)
    return _MMS_SPACES_RE.sub(" ", squashed).strip()


def _option_label(language: str, idx: int) -> str:
    """Return the spoken label for option at ``idx`` (0-based).

    French uses the Latin letter (OpenAI TTS handles "A"/"B"/"C" fine).
    MMS languages use a native ordinal word — saying "a"/"b" after MMS's
    lowercase-normalize produces sub-audible output and users cannot
    tell options apart (#1719). Falls back to the last ordinal if a
    question has more options than we have ordinals cached.
    """
    if language == "fr":
        return chr(ord("A") + idx)
    ordinals = _MMS_OPTION_ORDINALS.get(language, ())
    if not ordinals:
        return str(idx + 1)
    return ordinals[idx] if idx < len(ordinals) else ordinals[-1]


def build_audio_script(
    question: QBankQuestion,
    language: str,
    translation: QBankQuestionTranslation | None = None,
) -> str:
    """Return the text that should be spoken for a question.

    Prepends the option label in the speaker's language so the TTS reads
    "Option A: ..." in French and the native prefix + ordinal in MMS
    languages ("sugandili kelen" for dyu option 1, etc.).

    When ``translation`` is provided (#1690), its translated question_text
    and options are used instead of the source-language ones. Without it
    the raw ``question.question_text`` falls through, which is correct
    for ``fr`` (source) but produces gibberish if fed into an MMS model
    for mos/dyu/bam/ful.

    For MMS target languages the final script is passed through
    ``_normalize_for_mms`` so the per-language character vocab sees only
    tokens it can encode (#1719).
    """
    prefixes = {
        "fr": "Option",
        "mos": "Tʋʋmde",  # Moore: "task/choice"
        "dyu": "Sugandili",  # Dioula/Jula: "choice"
        "bam": "Sugandili",  # Bambara: "choice"
        "ful": "Suɓaande",  # Fulfulde: "choice"
    }
    prefix = prefixes.get(language, "Option")

    if translation is not None:
        q_text = (translation.question_text or "").strip()
        options = list(translation.options or [])
    else:
        q_text = (question.question_text or "").strip()
        options = list(question.options or [])

    parts = [q_text]
    for idx, opt in enumerate(options):
        label = _option_label(language, idx)
        parts.append(f"{prefix} {label}: {opt}")
    script = ". ".join(p for p in parts if p).strip() + "."

    if language != "fr":
        script = _normalize_for_mms(script)
    return script


def build_audio_segments(
    question: QBankQuestion,
    language: str,
    translation: QBankQuestionTranslation | None = None,
) -> list[str]:
    """Return a list of sentence-sized chunks for per-segment MMS synth.

    MMS VITS models produce clearer prosody on short inputs and we want
    an audible pause between the question and each option so the listener
    can parse the structure (#1719). Each returned chunk is already
    normalized for the MMS tokenizer.

    French uses a single-blob path (OpenAI TTS is fine with long text);
    for ``fr`` this returns a one-element list.
    """
    prefixes = {
        "fr": "Option",
        "mos": "Tʋʋmde",
        "dyu": "Sugandili",
        "bam": "Sugandili",
        "ful": "Suɓaande",
    }
    prefix = prefixes.get(language, "Option")

    if translation is not None:
        q_text = (translation.question_text or "").strip()
        options = list(translation.options or [])
    else:
        q_text = (question.question_text or "").strip()
        options = list(question.options or [])

    raw_segments: list[str] = []
    # The question may itself contain multiple sentences (e.g. when the
    # source French has line breaks collapsed into ". "); split on
    # sentence-terminators before we strip them.
    for sub in _SENTENCE_SPLIT_RE.split(q_text):
        if sub.strip():
            raw_segments.append(sub.strip())
    for idx, opt in enumerate(options):
        if not opt or not opt.strip():
            continue
        label = _option_label(language, idx)
        raw_segments.append(f"{prefix} {label}: {opt.strip()}")

    if language == "fr":
        return [". ".join(raw_segments).strip() + "."] if raw_segments else []
    # For MMS langs, normalize each segment individually. Empty results
    # (e.g. a stray punctuation-only chunk) are dropped.
    normalized = [_normalize_for_mms(s) for s in raw_segments]
    return [s for s in normalized if s]


def estimate_duration_seconds(audio_bytes: int) -> int:
    """Estimate OGG/Opus clip duration from byte size (speech @ ~48 kbps)."""
    return max(1, audio_bytes // OPUS_BYTES_PER_SECOND)


class QBankAudioService:
    """Generate and store TTS audio for qbank questions."""

    def __init__(self, mms_client: MMSTTSClient | None = None) -> None:
        self._mms = mms_client or MMSTTSClient()
        self._storage = S3StorageService()

    def _storage_key(self, bank_id: uuid.UUID, question_id: uuid.UUID, language: str) -> str:
        return f"qbank-audio/{bank_id}/{question_id}/{language}.opus"

    async def _upsert_audio_row(
        self,
        db: AsyncSession,
        question_id: uuid.UUID,
        language: str,
        **updates: object,
    ) -> QBankQuestionAudio:
        """Create or update the (question, language) audio row.

        Callers in the TTS generation path pass ``_skip_manual=True`` so
        we return the existing manual row unchanged instead of flipping
        it back to ``tts``/``generating`` — protects human recordings
        from being overwritten on the next pregeneration pass (#1747).
        """
        skip_manual = bool(updates.pop("_skip_manual", False))
        existing = await db.execute(
            select(QBankQuestionAudio).where(
                QBankQuestionAudio.question_id == question_id,
                QBankQuestionAudio.language == language,
            )
        )
        row = existing.scalar_one_or_none()
        if row is not None and skip_manual and row.source == QBankAudioSource.manual:
            return row
        if row is None:
            row = QBankQuestionAudio(question_id=question_id, language=language)
            db.add(row)
        for field, value in updates.items():
            setattr(row, field, value)
        await db.commit()
        await db.refresh(row)
        return row

    async def _synthesize_bytes(self, script: str, language: str) -> bytes:
        """Dispatch to the right TTS backend and return OGG/Opus bytes."""
        if language == "fr":
            from openai import AsyncOpenAI

            client = AsyncOpenAI(api_key=settings.openai_api_key)
            response = await client.audio.speech.create(
                model="gpt-4o-mini-tts",
                voice="nova",
                input=script,
                response_format="opus",
            )
            audio = response.content
            if not audio:
                raise ValueError("OpenAI TTS returned empty audio")
            return audio

        if MMSTTSClient.supports(language):
            return await self._mms.synthesize(script, language)

        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported audio language: {language}",
        )

    async def _synthesize_segments(self, segments: list[str], language: str) -> bytes:
        """Synthesize each segment individually and splice with silence.

        MMS VITS produces flatter prosody on long inputs, so we break the
        question + options into one clip per sentence and concatenate
        with 300ms silence between. This also restores the
        "end of thought" cue that punctuation would have carried if MMS
        tokenizers could encode it (#1719).

        French takes the single-blob path — OpenAI TTS is fine with long
        text and silence-splicing its output wouldn't pay off.

        Splicing uses pydub (+ ffmpeg). If either isn't available in the
        runtime image (the backend container ships without ffmpeg today),
        gracefully fall back to a single MMS call on the joined
        segments — the ordinal labels and punctuation normalization still
        take effect, just without the explicit inter-segment silence.
        """
        if not segments:
            raise MMSTTSError("no segments to synthesize")
        if language == "fr" or len(segments) == 1:
            return await self._synthesize_bytes(segments[0], language)

        try:
            import io

            from pydub import AudioSegment
        except ImportError:
            logger.info(
                "pydub unavailable; falling back to single-blob MMS call",
                language=language,
                segments=len(segments),
            )
            return await self._synthesize_bytes(" ".join(segments), language)

        # Per-segment MMS calls. Backend MMS client already has a
        # Semaphore(2); we just call sequentially within one task to
        # keep the sidecar from being overwhelmed.
        clips: list[bytes] = []
        for seg in segments:
            clips.append(await self._mms.synthesize(seg, language))

        try:
            audio_parts = [AudioSegment.from_file(io.BytesIO(b), format="ogg") for b in clips]
            silence = AudioSegment.silent(duration=_SEGMENT_SILENCE_MS)
            combined = audio_parts[0]
            for part in audio_parts[1:]:
                combined = combined + silence + part
            buf = io.BytesIO()
            combined.export(
                buf,
                format="ogg",
                codec="libopus",
                bitrate="24k",
                parameters=["-application", "voip"],
            )
            return buf.getvalue()
        except FileNotFoundError as exc:
            # pydub is installed but ffmpeg/libopus isn't — same
            # fallback. Log once so we can track how often this path
            # runs in prod.
            logger.warning(
                "pydub splice failed (likely missing ffmpeg); using joined single call",
                language=language,
                error=str(exc),
            )
            return await self._synthesize_bytes(" ".join(segments), language)

    async def generate_question_audio(
        self,
        db: AsyncSession,
        question_id: uuid.UUID,
        language: str,
    ) -> QBankQuestionAudio:
        """Generate audio for a single question in one language.

        For non-source languages (mos/dyu/bam/ful), translates the
        question + options via NLLB first so the MMS sidecar receives
        native-language text and produces intelligible speech (#1690).
        Sets status ``generating`` while running and ``ready`` / ``failed``
        afterwards so the frontend poll endpoint can reflect progress.
        """
        question = await db.get(QBankQuestion, question_id)
        if question is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Question not found.")

        # Short-circuit if the editor already uploaded a manual clip for
        # this (question, language) — the existing recording takes
        # precedence over anything TTS would produce (#1747).
        existing = await self.get_audio_status(db, question_id, language)
        if existing is not None and existing.source == QBankAudioSource.manual:
            return existing

        await self._upsert_audio_row(
            db,
            question_id,
            language,
            status=QBankAudioStatus.generating,
            _skip_manual=True,
        )

        # Translate FR → target before TTS for all non-source languages.
        # Translation fetch is idempotent; on NLLB failure we mark audio
        # as failed rather than falling back to French-in-MMS (the broken
        # behavior that shipped in #1670 and was fixed by #1681/#1690).
        translation: QBankQuestionTranslation | None = None
        if language != "fr":
            from app.domain.services.qbank_translation_service import (
                QBankTranslationService,
            )

            try:
                translation = await QBankTranslationService().ensure_translation(
                    db, question_id, language
                )
            except NLLBTranslateError as exc:
                logger.warning(
                    "NLLB translation failed",
                    question_id=str(question_id),
                    language=language,
                    error=str(exc),
                )
                return await self._upsert_audio_row(
                    db,
                    question_id,
                    language,
                    status=QBankAudioStatus.failed,
                    _skip_manual=True,
                )

        try:
            segments = build_audio_segments(question, language, translation=translation)
            if not segments:
                raise ValueError("empty audio script")
            audio_bytes = await self._synthesize_segments(segments, language)
            key = self._storage_key(question.question_bank_id, question_id, language)
            url = await self._storage.upload_bytes(
                key=key, data=audio_bytes, content_type=OPUS_CONTENT_TYPE
            )
        except MMSTTSError as exc:
            logger.warning("MMS synthesis failed", question_id=str(question_id), error=str(exc))
            return await self._upsert_audio_row(
                db,
                question_id,
                language,
                status=QBankAudioStatus.failed,
                _skip_manual=True,
            )
        except Exception as exc:
            logger.exception(
                "qbank audio generation failed",
                question_id=str(question_id),
                language=language,
                error=str(exc),
            )
            return await self._upsert_audio_row(
                db,
                question_id,
                language,
                status=QBankAudioStatus.failed,
                _skip_manual=True,
            )

        return await self._upsert_audio_row(
            db,
            question_id,
            language,
            storage_key=key,
            storage_url=url,
            duration_seconds=estimate_duration_seconds(len(audio_bytes)),
            status=QBankAudioStatus.ready,
            source=QBankAudioSource.tts,
            content_type=OPUS_CONTENT_TYPE,
            _skip_manual=True,
        )

    async def batch_generate(
        self,
        db: AsyncSession,
        bank_id: uuid.UUID,
        language: str,
        *,
        skip_ready: bool = True,
    ) -> dict:
        """Generate audio for every question in a bank. Intended for Celery.

        Idempotent by default: questions whose ``(question, language)`` row
        is already ``ready`` are skipped so republishing or retrying a
        bank doesn't re-bill TTS for clips that already exist (#1674).
        """
        bank = await db.get(QuestionBank, bank_id)
        if bank is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Question bank not found.",
            )

        questions = (
            (
                await db.execute(
                    select(QBankQuestion).where(QBankQuestion.question_bank_id == bank_id)
                )
            )
            .scalars()
            .all()
        )

        ready_question_ids: set[uuid.UUID] = set()
        manual_question_ids: set[uuid.UUID] = set()
        if questions:
            existing = await db.execute(
                select(QBankQuestionAudio).where(
                    QBankQuestionAudio.question_id.in_([q.id for q in questions]),
                    QBankQuestionAudio.language == language,
                )
            )
            for row in existing.scalars():
                if row.source == QBankAudioSource.manual:
                    # Editor-provided clip — never touched by TTS batch (#1747).
                    manual_question_ids.add(row.question_id)
                elif skip_ready and row.status == QBankAudioStatus.ready:
                    ready_question_ids.add(row.question_id)

        ready = 0
        failed = 0
        skipped = 0
        manual = 0
        for q in questions:
            if q.id in manual_question_ids:
                manual += 1
                ready += 1  # Manual clips are always considered ready.
                continue
            if q.id in ready_question_ids:
                skipped += 1
                ready += 1  # Already-ready TTS clips still count as ready.
                continue
            row = await self.generate_question_audio(db, q.id, language)
            if row.status == QBankAudioStatus.ready:
                ready += 1
            else:
                failed += 1

        return {
            "bank_id": str(bank_id),
            "language": language,
            "total": len(questions),
            "skipped": skipped,
            "manual": manual,
            "ready": ready,
            "failed": failed,
        }

    async def invalidate_question(
        self,
        db: AsyncSession,
        question_id: uuid.UUID,
    ) -> None:
        """Drop every cached TTS audio row for a question.

        Called when a question's text or options change — the stored
        clip no longer matches the script and must be regenerated.
        Manual recordings are preserved: the editor chose that take
        deliberately and we'd rather play outdated audio than silently
        discard a human recording (#1747). The editor can delete the
        manual row explicitly via the admin UI if needed.
        """
        await db.execute(
            QBankQuestionAudio.__table__.delete().where(
                QBankQuestionAudio.question_id == question_id,
                QBankQuestionAudio.source != QBankAudioSource.manual,
            )
        )
        await db.commit()

    async def delete_question_audio(
        self,
        db: AsyncSession,
        question_id: uuid.UUID,
        language: str,
    ) -> None:
        """Remove a single (question, language) audio row and its MinIO object.

        Lets an editor clear a manual recording so the TTS pipeline can
        refill the slot on the next generate/backfill (#1747).
        """
        row = await self.get_audio_status(db, question_id, language)
        if row is None:
            return
        if row.storage_key:
            try:
                await self._storage.delete_object(row.storage_key)
            except Exception as exc:
                logger.warning(
                    "failed to delete audio object from storage",
                    question_id=str(question_id),
                    language=language,
                    key=row.storage_key,
                    error=str(exc),
                )
        await db.execute(
            QBankQuestionAudio.__table__.delete().where(
                QBankQuestionAudio.id == row.id,
            )
        )
        await db.commit()

    async def store_uploaded_audio(
        self,
        db: AsyncSession,
        question_id: uuid.UUID,
        language: str,
        audio_bytes: bytes,
        content_type: str,
    ) -> QBankQuestionAudio:
        """Store a human-recorded or file-uploaded clip (#1747).

        Marks the row ``source='manual'`` so subsequent TTS batch runs
        skip it. The original MIME is persisted so the playback endpoint
        can return the right Content-Type — editors may upload webm,
        mp3, m4a or wav in addition to OGG/Opus.
        """
        question = await db.get(QBankQuestion, question_id)
        if question is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Question not found.")
        key = self._storage_key(question.question_bank_id, question_id, language)
        url = await self._storage.upload_bytes(key=key, data=audio_bytes, content_type=content_type)
        return await self._upsert_audio_row(
            db,
            question_id,
            language,
            storage_key=key,
            storage_url=url,
            duration_seconds=estimate_duration_seconds(len(audio_bytes)),
            status=QBankAudioStatus.ready,
            source=QBankAudioSource.manual,
            content_type=content_type,
        )

    async def get_audio_status(
        self,
        db: AsyncSession,
        question_id: uuid.UUID,
        language: str,
    ) -> QBankQuestionAudio | None:
        result = await db.execute(
            select(QBankQuestionAudio).where(
                QBankQuestionAudio.question_id == question_id,
                QBankQuestionAudio.language == language,
            )
        )
        return result.scalar_one_or_none()
