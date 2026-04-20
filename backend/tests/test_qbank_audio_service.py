"""Unit tests for qbank audio helpers + TTS dispatch.

DB/MinIO paths are intentionally out of scope — they're thin wrappers over
already-tested primitives. These tests pin down the behaviors that matter:
the spoken script format, size estimation, and the fact that unsupported
languages don't hit any TTS backend.
"""

from __future__ import annotations

import types
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.domain.models.question_bank import (
    QBankAudioSource,
    QBankAudioStatus,
)
from app.domain.services.qbank_audio_service import (
    SUPPORTED_LANGUAGES,
    QBankAudioService,
    build_audio_script,
    build_audio_segments,
    estimate_duration_seconds,
)


class _FakeQuestion:
    def __init__(self, text: str, options: list[str]):
        self.question_text = text
        self.options = options


def test_build_audio_script_french_prefix():
    q = _FakeQuestion("Que signifie ce panneau ?", ["Stop", "Céder", "Danger"])
    script = build_audio_script(q, "fr")
    assert script.startswith("Que signifie ce panneau ?")
    assert "Option A: Stop" in script
    assert "Option B: Céder" in script
    assert "Option C: Danger" in script
    assert script.endswith(".")


def test_build_audio_script_mms_languages_use_ordinal_word_labels():
    # MMS VITS vocab is lowercase-only, no punctuation, and can't
    # distinguish single-letter labels "a" / "b" when pronounced. We use
    # native ordinal words instead so the listener hears a clear
    # difference between options (#1719).
    q = _FakeQuestion("Question", ["A", "B"])
    expectations = [
        ("mos", "tʋʋmde", "pipi", "yiibu"),
        ("dyu", "sugandili", "kelen", "fila"),
        ("bam", "sugandili", "kelen", "fila"),
        ("ful", "suɓaande", "goo", "ɗiɗi"),
    ]
    for lang, prefix, ord1, ord2 in expectations:
        script = build_audio_script(q, lang)
        assert f"{prefix} {ord1}" in script
        assert f"{prefix} {ord2}" in script
        # No punctuation the MMS tokenizer cannot encode.
        for bad in ("?", ".", ":", ",", ";", "!"):
            assert bad not in script
        # No uppercase letters either.
        assert script == script.lower()


def test_build_audio_script_mms_strips_punctuation_from_translation():
    """Real-world case: stored dyu translation has `?` and `'` etc."""
    from types import SimpleNamespace

    q = _FakeQuestion("QUE T'INDIQUE CE PANNEAU ?", ["Oui.", "Non."])
    tr = SimpleNamespace(
        question_text="I ka kan k'a kɛ cogo di o koo ɲɔgɔn na?",
        options=["O ye mun lo yira i la?", "A b'a fɔ i ye."],
    )
    script = build_audio_script(q, "dyu", translation=tr)
    # Apostrophe survives (in MMS vocab); question mark stripped to space.
    assert "k'a" in script
    assert "ɲɔgɔn" in script
    assert "?" not in script
    assert script == script.lower()
    # Collapsed spaces — no double spaces.
    assert "  " not in script
    # Ordinal labels used instead of letters.
    assert "sugandili kelen" in script
    assert "sugandili fila" in script


def test_build_audio_segments_dyu_splits_question_and_options():
    """Each sentence becomes its own segment so we can splice silence."""
    from types import SimpleNamespace

    q = _FakeQuestion("QUE T'INDIQUE CE PANNEAU ?", ["Oui.", "Non."])
    tr = SimpleNamespace(
        question_text="I ka kan k'a kɛ cogo di o koo ɲɔgɔn na?",
        options=["O ye mun lo yira i la?", "A b'a fɔ i ye."],
    )
    segments = build_audio_segments(q, "dyu", translation=tr)
    # Question + 2 options → 3 segments.
    assert len(segments) == 3
    assert all(s == s.lower() for s in segments)
    assert segments[0].startswith("i ka kan k'a kɛ")
    assert segments[1].startswith("sugandili kelen")
    assert segments[2].startswith("sugandili fila")
    for s in segments:
        for bad in ("?", ".", ":", ","):
            assert bad not in s


def test_build_audio_segments_fr_returns_single_blob():
    q = _FakeQuestion("Question française", ["Oui", "Non"])
    segments = build_audio_segments(q, "fr")
    assert len(segments) == 1
    assert "Option A: Oui" in segments[0]
    assert "Option B: Non" in segments[0]


def test_build_audio_script_handles_empty_options():
    q = _FakeQuestion("Just a question", [])
    script = build_audio_script(q, "fr")
    assert script == "Just a question."


def test_estimate_duration_seconds_opus_rate():
    # 30s clip at ~48 kbps = ~180 KB
    assert estimate_duration_seconds(180 * 1024) == 30
    # Always returns at least 1 second for tiny blobs
    assert estimate_duration_seconds(10) == 1


@pytest.mark.asyncio
async def test_synthesize_rejects_unsupported_language():
    svc = QBankAudioService(
        mms_client=types.SimpleNamespace(
            synthesize=AsyncMock(side_effect=AssertionError("should not be called")),
        )
    )
    with pytest.raises(HTTPException) as exc:
        await svc._synthesize_bytes("hi", "en")
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_synthesize_dispatches_mms_languages_to_client():
    fake_mms = types.SimpleNamespace(synthesize=AsyncMock(return_value=b"OGG"))
    svc = QBankAudioService(mms_client=fake_mms)
    out = await svc._synthesize_bytes("lakala", "dyu")
    assert out == b"OGG"
    fake_mms.synthesize.assert_awaited_once_with("lakala", "dyu")


def test_supported_languages_is_non_empty_tuple():
    # Pregeneration loops over this tuple, so it must stay iterable and
    # contain at least French (the baseline).
    assert isinstance(SUPPORTED_LANGUAGES, tuple)
    assert "fr" in SUPPORTED_LANGUAGES
    assert all(isinstance(lang, str) for lang in SUPPORTED_LANGUAGES)


# ---------------------------------------------------------------------------
# Manual audio override (#1747)
# ---------------------------------------------------------------------------


async def _seed_bank_and_question(db_session):
    """Create a minimal bank + one question + a creator user."""
    import uuid as _uuid

    from app.domain.models.organization import Organization
    from app.domain.models.question_bank import (
        QBankQuestion,
        QuestionBank,
        QuestionBankType,
    )
    from app.domain.models.user import User, UserRole

    slug_suffix = _uuid.uuid4().hex[:8]
    org = Organization(
        id=_uuid.uuid4(),
        name="Test Org",
        slug=f"test-org-{slug_suffix}",
    )
    db_session.add(org)
    user = User(
        id=_uuid.uuid4(),
        email=f"{slug_suffix}@example.com",
        name="Test Editor",
        role=UserRole.admin,
    )
    db_session.add(user)
    await db_session.flush()

    bank = QuestionBank(
        id=_uuid.uuid4(),
        organization_id=org.id,
        title="Test Bank",
        bank_type=QuestionBankType.driving,
        created_by=user.id,
    )
    db_session.add(bank)
    await db_session.flush()

    question = QBankQuestion(
        id=_uuid.uuid4(),
        question_bank_id=bank.id,
        order_index=1,
        question_text="Test question?",
        options=["A", "B"],
        correct_answer_indices=[0],
    )
    db_session.add(question)
    await db_session.commit()
    return bank, question


@pytest.mark.asyncio
async def test_store_uploaded_audio_sets_source_manual(db_session):
    """Uploads land with ``source=manual`` and the MIME the editor sent."""
    fake_storage = types.SimpleNamespace(
        upload_bytes=AsyncMock(return_value="http://minio:9000/k"),
        delete_object=AsyncMock(),
    )
    svc = QBankAudioService()
    svc._storage = fake_storage

    _, question = await _seed_bank_and_question(db_session)
    row = await svc.store_uploaded_audio(
        db_session,
        question.id,
        "fr",
        b"fake-webm-bytes",
        "audio/webm",
    )
    assert row.source == QBankAudioSource.manual
    assert row.status == QBankAudioStatus.ready
    assert row.content_type == "audio/webm"
    fake_storage.upload_bytes.assert_awaited_once()


@pytest.mark.asyncio
async def test_generate_question_audio_skips_manual_row(db_session):
    """TTS path short-circuits when a manual clip already exists (#1747)."""
    fake_storage = types.SimpleNamespace(
        upload_bytes=AsyncMock(return_value="http://minio:9000/k"),
        delete_object=AsyncMock(),
    )
    svc = QBankAudioService()
    svc._storage = fake_storage
    svc._synthesize_segments = AsyncMock(
        side_effect=AssertionError("TTS must not run when source=manual"),
    )

    _, question = await _seed_bank_and_question(db_session)
    manual_row = await svc.store_uploaded_audio(
        db_session,
        question.id,
        "fr",
        b"manual-bytes",
        "audio/webm",
    )

    returned = await svc.generate_question_audio(db_session, question.id, "fr")
    assert returned.id == manual_row.id
    assert returned.source == QBankAudioSource.manual
    assert returned.content_type == "audio/webm"


@pytest.mark.asyncio
async def test_batch_generate_counts_manual_rows_without_synthesizing(db_session):
    """Manual clips are counted as ready and never hit the TTS backend."""
    fake_storage = types.SimpleNamespace(
        upload_bytes=AsyncMock(return_value="http://minio:9000/k"),
        delete_object=AsyncMock(),
    )
    svc = QBankAudioService()
    svc._storage = fake_storage
    svc._synthesize_segments = AsyncMock(
        side_effect=AssertionError("batch must not synth manual rows"),
    )

    bank, question = await _seed_bank_and_question(db_session)
    await svc.store_uploaded_audio(
        db_session,
        question.id,
        "fr",
        b"manual",
        "audio/webm",
    )

    result = await svc.batch_generate(db_session, bank.id, "fr")
    assert result["total"] == 1
    assert result["manual"] == 1
    assert result["ready"] == 1
    assert result["failed"] == 0


@pytest.mark.asyncio
async def test_invalidate_question_preserves_manual_clip(db_session):
    """Question-text edits drop TTS rows but keep manual recordings (#1747)."""
    from sqlalchemy import select

    from app.domain.models.question_bank import QBankQuestionAudio

    fake_storage = types.SimpleNamespace(
        upload_bytes=AsyncMock(return_value="http://minio:9000/k"),
        delete_object=AsyncMock(),
    )
    svc = QBankAudioService()
    svc._storage = fake_storage

    _, question = await _seed_bank_and_question(db_session)
    await svc._upsert_audio_row(
        db_session,
        question.id,
        "fr",
        status=QBankAudioStatus.ready,
        source=QBankAudioSource.tts,
        storage_key="tts-key",
        storage_url="http://minio:9000/tts",
        content_type="audio/ogg",
    )
    await svc.store_uploaded_audio(
        db_session,
        question.id,
        "mos",
        b"manual",
        "audio/webm",
    )

    await svc.invalidate_question(db_session, question.id)

    remaining = (
        (
            await db_session.execute(
                select(QBankQuestionAudio).where(
                    QBankQuestionAudio.question_id == question.id,
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(remaining) == 1
    assert remaining[0].language == "mos"
    assert remaining[0].source == QBankAudioSource.manual


@pytest.mark.asyncio
async def test_delete_question_audio_removes_row_and_storage(db_session):
    """``delete_question_audio`` nukes the row + best-effort MinIO delete."""
    from sqlalchemy import select

    from app.domain.models.question_bank import QBankQuestionAudio

    fake_storage = types.SimpleNamespace(
        upload_bytes=AsyncMock(return_value="http://minio:9000/k"),
        delete_object=AsyncMock(),
    )
    svc = QBankAudioService()
    svc._storage = fake_storage

    _, question = await _seed_bank_and_question(db_session)
    await svc.store_uploaded_audio(
        db_session,
        question.id,
        "fr",
        b"bytes",
        "audio/webm",
    )

    await svc.delete_question_audio(db_session, question.id, "fr")

    fake_storage.delete_object.assert_awaited_once()
    remaining = (
        (
            await db_session.execute(
                select(QBankQuestionAudio).where(
                    QBankQuestionAudio.question_id == question.id,
                    QBankQuestionAudio.language == "fr",
                )
            )
        )
        .scalars()
        .all()
    )
    assert remaining == []
