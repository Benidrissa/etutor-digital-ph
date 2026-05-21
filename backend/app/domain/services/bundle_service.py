"""BundleService — renders course content to self-contained HTML and assembles a flat ZIP."""

from __future__ import annotations

import base64
import io
import uuid
import zipfile
from datetime import UTC, datetime
from html import escape
from typing import TYPE_CHECKING

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.schemas.content import CaseStudyResponse, LessonResponse, SourceImageRef
from app.api.v1.schemas.quiz import QuizResponse
from app.domain.models.generated_audio import GeneratedAudio
from app.domain.models.source_image import SourceImage
from app.infrastructure.storage.s3 import S3StorageService

if TYPE_CHECKING:
    pass

logger = structlog.get_logger(__name__)

_CSS = """
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
body{font-family:Georgia,serif;max-width:800px;margin:0 auto;padding:2rem 1rem;color:#1a1a1a;line-height:1.7}
header{border-bottom:2px solid #166534;padding-bottom:1rem;margin-bottom:2rem}
.breadcrumb{font-size:.85rem;color:#6b7280;margin-bottom:.4rem}
h1{font-size:1.4rem;color:#166534;margin-bottom:.2rem}
h2{font-size:1.15rem;color:#166534;margin:1.5rem 0 .6rem}
h3{font-size:1rem;color:#374151;margin:.9rem 0 .4rem;font-weight:700}
.meta{font-size:.78rem;color:#9ca3af;margin-top:.25rem}
.badge{display:inline-block;padding:.15rem .5rem;border-radius:99px;font-size:.75rem;font-weight:600;margin-left:.4rem;vertical-align:middle}
section{margin:1.4rem 0}
.intro{background:#f0fdf4;padding:1rem;border-left:4px solid #166534;border-radius:0 4px 4px 0}
.example{background:#fef9c3;padding:1rem;border-left:4px solid #ca8a04;border-radius:0 4px 4px 0}
.synthesis{background:#f0f9ff;padding:1rem;border-left:4px solid #0284c7;border-radius:0 4px 4px 0}
.key-points{padding-left:1.4rem}
.key-points li{margin:.4rem 0}
figure{margin:1.4rem 0;text-align:center}
figure img{max-width:100%;height:auto;border-radius:4px;box-shadow:0 1px 4px rgba(0,0,0,.12)}
figcaption{font-size:.82rem;color:#6b7280;margin-top:.4rem;font-style:italic}
.quiz-meta{font-size:.85rem;color:#6b7280;margin-bottom:1rem}
.question{border:1px solid #e5e7eb;border-radius:6px;padding:1rem;margin:1rem 0}
.question-text{font-weight:600;margin-bottom:.75rem}
.option{padding:.45rem .7rem;border-radius:4px;margin:.2rem 0;font-size:.95rem}
.option.correct{background:#dcfce7;border-left:3px solid #16a34a}
.option.other{color:#6b7280}
.explanation{margin-top:.75rem;font-size:.88rem;color:#374151;background:#f9fafb;padding:.7rem;border-radius:4px}
.diff-easy{background:#dcfce7;color:#16a34a}
.diff-medium{background:#fef9c3;color:#ca8a04}
.diff-hard{background:#fee2e2;color:#dc2626}
.case-context,.case-correction{background:#f9fafb;padding:1rem;border:1px solid #e5e7eb;border-radius:4px}
.case-data{font-family:monospace;font-size:.88rem;background:#f9fafb;padding:1rem;border:1px solid #e5e7eb;border-radius:4px;white-space:pre-wrap}
.guided-questions{counter-reset:gq;padding:0}
.guided-questions li{counter-increment:gq;padding:.6rem 1rem .6rem 2.2rem;background:#f0fdf4;border-radius:4px;margin:.4rem 0;list-style:none;position:relative}
.guided-questions li::before{content:counter(gq)".";position:absolute;left:.7rem;font-weight:700;color:#166534}
.flashcard{border:1px solid #e5e7eb;border-radius:8px;padding:1.1rem;margin:.9rem 0}
.flashcard-term{font-size:1.05rem;font-weight:700;color:#166534;border-bottom:1px solid #dcfce7;padding-bottom:.4rem;margin-bottom:.6rem}
.flashcard-def{margin:.35rem 0}
.flashcard-def b{color:#374151}
audio{width:100%;margin-top:.75rem}
.sources-list{margin-top:1.5rem;padding-top:.75rem;border-top:1px solid #e5e7eb;font-size:.78rem;color:#9ca3af}
footer{margin-top:2.5rem;padding-top:.75rem;border-top:1px solid #e5e7eb;font-size:.78rem;color:#9ca3af;text-align:center}
@media print{body{padding:0}footer{display:none}}
@media(max-width:600px){body{padding:1rem .75rem}h1{font-size:1.2rem}}
"""


def _html_shell(
    lang: str,
    title: str,
    breadcrumb: str,
    meta_line: str,
    body_html: str,
    sources: list[str],
) -> str:
    sources_html = ""
    if sources:
        items = "".join(f"<li>{escape(s)}</li>" for s in sources)
        label = "Sources" if lang == "en" else "Sources"
        sources_html = f'<div class="sources-list"><strong>{label}</strong><ul>{items}</ul></div>'

    date_str = datetime.now(UTC).strftime("%Y-%m-%d")
    footer_text = f"Sira · {date_str}"

    return f"""<!DOCTYPE html>
<html lang="{lang}">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(title)}</title>
<style>{_CSS}</style>
</head>
<body>
<header>
  <div class="breadcrumb">{escape(breadcrumb)}</div>
  <h1>{escape(title)}</h1>
  <div class="meta">{meta_line}</div>
</header>
<main>
{body_html}
{sources_html}
</main>
<footer>{footer_text}</footer>
</body>
</html>"""


def _embed_image(img_bytes: bytes, fmt: str = "webp", alt: str = "") -> str:
    b64 = base64.b64encode(img_bytes).decode()
    mime = "image/png" if fmt == "png" else "image/webp"
    return f'<img src="data:{mime};base64,{b64}" alt="{escape(alt)}" loading="lazy">'


def _embed_audio(audio_bytes: bytes) -> str:
    b64 = base64.b64encode(audio_bytes).decode()
    label_html = '<p style="font-size:.85rem;color:#6b7280;margin-bottom:.3rem">🔊 Audio</p>'
    return (
        f"{label_html}"
        f'<audio controls>'
        f'<source src="data:audio/ogg;base64,{b64}" type="audio/ogg; codecs=opus">'
        f"</audio>"
    )


async def _fetch_source_images(
    refs: list[SourceImageRef],
    lang: str,
    session: AsyncSession,
    storage: S3StorageService,
) -> dict[str, tuple[bytes, str, str]]:
    """Return {image_id: (bytes, fmt, alt_text)} for each resolvable ref."""
    result: dict[str, tuple[bytes, str, str]] = {}
    for ref in refs:
        try:
            img = await session.get(SourceImage, uuid.UUID(ref.id))
            if img is None:
                continue
            key = img.storage_key_fr if (lang == "fr" and img.storage_key_fr) else img.storage_key
            if not key:
                continue
            data = await storage.download_bytes(key)
            alt = (ref.alt_text_fr if lang == "fr" else ref.alt_text_en) or ref.caption or ""
            result[ref.id] = (data, img.format or "webp", alt)
        except Exception as exc:
            logger.warning("bundle.image_fetch_failed", image_id=ref.id, error=str(exc))
    return result


async def _fetch_audio(
    module_id: uuid.UUID,
    unit_id: str,
    lang: str,
    session: AsyncSession,
    storage: S3StorageService,
) -> bytes | None:
    try:
        row = (
            await session.execute(
                select(GeneratedAudio)
                .where(
                    GeneratedAudio.module_id == module_id,
                    GeneratedAudio.unit_id == unit_id,
                    GeneratedAudio.language == lang,
                    GeneratedAudio.status == "ready",
                    GeneratedAudio.media_type == "audio",
                )
                .limit(1)
            )
        ).scalars().first()
        if row is None or not row.storage_key:
            return None
        return await storage.download_bytes(row.storage_key)
    except Exception as exc:
        logger.warning(
            "bundle.audio_fetch_failed", module_id=str(module_id), unit_id=unit_id, error=str(exc)
        )
        return None


def _level_label(level: int, lang: str) -> str:
    labels_fr = {1: "Débutant", 2: "Intermédiaire", 3: "Avancé", 4: "Expert"}
    labels_en = {1: "Beginner", 2: "Intermediate", 3: "Advanced", 4: "Expert"}
    d = labels_fr if lang == "fr" else labels_en
    return d.get(level, str(level))


class BundleService:
    def __init__(self) -> None:
        self._storage = S3StorageService()

    async def render_lesson(
        self,
        resp: LessonResponse,
        module_title: str,
        unit_title: str,
        course_title: str,
        session: AsyncSession,
    ) -> str:
        lang = resp.language
        level = resp.level
        c = resp.content

        images = await _fetch_source_images(resp.source_image_refs, lang, session, self._storage)
        audio = await _fetch_audio(resp.module_id, resp.unit_id, lang, session, self._storage)

        # --- Build image HTML fragments indexed by ref.id ---
        img_frags: dict[str, str] = {}
        for ref in resp.source_image_refs:
            if ref.id not in images:
                continue
            data, fmt, alt = images[ref.id]
            caption = (ref.caption_fr if lang == "fr" else ref.caption_en) or ref.caption or ""
            img_tag = _embed_image(data, fmt, alt)
            cap_html = f"<figcaption>{escape(caption)}</figcaption>" if caption else ""
            img_frags[ref.id] = f"<figure>{img_tag}{cap_html}</figure>"

        figures_html = "".join(img_frags.values())
        concepts_html = "".join(
            f"<h3>{escape(c.concepts[i]) if i == 0 and len(c.concepts[0]) < 120 else ''}</h3>"
            f"<p>{escape(c.concepts[i])}</p>"
            if len(c.concepts[i]) >= 120
            else f"<p>{escape(c.concepts[i])}</p>"
            for i in range(len(c.concepts))
        )

        kp_items = "".join(f"<li>{escape(kp)}</li>" for kp in c.key_points)
        audio_html = _embed_audio(audio) if audio else ""
        type_label = "Leçon" if lang == "fr" else "Lesson"

        body = f"""
<section class="intro"><p>{escape(c.introduction)}</p></section>
<section>
  <h2>{"Concepts clés" if lang == "fr" else "Key Concepts"}</h2>
  {concepts_html}
</section>
{figures_html}
<section class="example">
  <h2>{"Exemple" if lang == "fr" else "Example"}</h2>
  <p>{escape(c.aof_example)}</p>
</section>
<section class="synthesis">
  <h2>{"Synthèse" if lang == "fr" else "Synthesis"}</h2>
  <p>{escape(c.synthesis)}</p>
</section>
<section>
  <h2>{"Points clés" if lang == "fr" else "Key Points"}</h2>
  <ul class="key-points">{kp_items}</ul>
</section>
{audio_html}
"""
        meta = f'<span class="badge diff-easy">{type_label}</span> · {_level_label(level, lang)}'
        return _html_shell(
            lang=lang,
            title=unit_title,
            breadcrumb=f"{course_title} › {module_title}",
            meta_line=meta,
            body_html=body,
            sources=c.sources_cited,
        )

    async def render_quiz(
        self,
        resp: QuizResponse,
        module_title: str,
        unit_title: str,
        course_title: str,
        session: AsyncSession,
    ) -> str:
        lang = resp.language
        level = resp.level
        c = resp.content

        questions_html = ""
        for q in c.questions:
            diff_cls = f"diff-{q.difficulty}" if q.difficulty in ("easy", "medium", "hard") else "diff-medium"
            diff_label = q.difficulty.capitalize()
            options_html = ""
            for i, opt in enumerate(q.options):
                cls = "correct" if i == q.correct_answer else "other"
                marker = "✓ " if i == q.correct_answer else ""
                options_html += f'<div class="option {cls}">{marker}{escape(opt)}</div>'
            exp_label = "Explication" if lang == "fr" else "Explanation"
            questions_html += f"""
<div class="question">
  <div class="question-text">{escape(q.question)}
    <span class="badge {diff_cls}">{diff_label}</span>
  </div>
  {options_html}
  <div class="explanation"><strong>{exp_label}:</strong> {escape(q.explanation)}</div>
</div>"""

        pass_label = "Score de passage" if lang == "fr" else "Passing score"
        time_label = "Limite de temps" if lang == "fr" else "Time limit"
        time_val = f"{c.time_limit_minutes} min" if c.time_limit_minutes else ("—" if lang == "en" else "—")
        type_label = "Quiz"
        meta = f'<span class="badge diff-medium">{type_label}</span> · {_level_label(level, lang)}'

        body = f"""
<div class="quiz-meta">
  {pass_label}: {int(c.passing_score)}% · {time_label}: {time_val} · {len(c.questions)} {"questions" if lang == "en" else "questions"}
</div>
<p>{escape(c.description)}</p>
{questions_html}
"""
        all_sources: list[str] = []
        for q in c.questions:
            all_sources.extend(q.sources_cited)

        return _html_shell(
            lang=lang,
            title=c.title,
            breadcrumb=f"{course_title} › {module_title} › {unit_title}",
            meta_line=meta,
            body_html=body,
            sources=list(dict.fromkeys(all_sources)),
        )

    async def render_case_study(
        self,
        resp: CaseStudyResponse,
        module_title: str,
        unit_title: str,
        course_title: str,
        session: AsyncSession,
    ) -> str:
        lang = resp.language
        level = resp.level
        c = resp.content

        gq_items = "".join(f"<li>{escape(q)}</li>" for q in c.guided_questions)
        type_label = "Étude de cas" if lang == "fr" else "Case Study"
        ctx_label = "Contexte" if lang == "fr" else "Context"
        data_label = "Données" if lang == "fr" else "Data"
        gq_label = "Questions guidées" if lang == "fr" else "Guided Questions"
        cor_label = "Correction annotée" if lang == "fr" else "Annotated Correction"
        meta = f'<span class="badge diff-hard">{type_label}</span> · {_level_label(level, lang)}'

        body = f"""
<section>
  <h2>{ctx_label}</h2>
  <div class="case-context"><p>{escape(c.aof_context)}</p></div>
</section>
<section>
  <h2>{data_label}</h2>
  <div class="case-data">{escape(c.real_data)}</div>
</section>
<section>
  <h2>{gq_label}</h2>
  <ol class="guided-questions">{gq_items}</ol>
</section>
<section>
  <h2>{cor_label}</h2>
  <div class="case-correction"><p>{escape(c.annotated_correction)}</p></div>
</section>
"""
        return _html_shell(
            lang=lang,
            title=unit_title,
            breadcrumb=f"{course_title} › {module_title}",
            meta_line=meta,
            body_html=body,
            sources=c.sources_cited,
        )

    async def render_flashcards(
        self,
        module_title: str,
        course_title: str,
        lang: str,
        level: int,
        flashcards: list,
    ) -> str:
        type_label = "Fiches" if lang == "fr" else "Flashcards"
        meta = f'<span class="badge diff-easy">{type_label}</span> · {_level_label(level, lang)}'

        cards_html = ""
        for fc in flashcards:
            defn = fc.definition_fr if lang == "fr" else fc.definition_en
            ex_label = "Exemple" if lang == "fr" else "Example"
            cards_html += f"""
<div class="flashcard">
  <div class="flashcard-term">{escape(fc.term)}</div>
  <div class="flashcard-def"><p>{escape(defn)}</p></div>
  <div class="flashcard-def"><b>{ex_label}:</b> {escape(fc.example_aof)}</div>
</div>"""

        title = f'{type_label} — {module_title}'
        return _html_shell(
            lang=lang,
            title=title,
            breadcrumb=f"{course_title} › {module_title}",
            meta_line=meta,
            body_html=cards_html,
            sources=[],
        )

    @staticmethod
    def build_zip(files: list[tuple[str, bytes]]) -> bytes:
        """Build a flat ZIP archive from (filename, content_bytes) pairs."""
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
            for name, data in files:
                zf.writestr(name, data)
        return buf.getvalue()
