"""Certificate PDF generation service — ReportLab-based A4 landscape certificates."""

from __future__ import annotations

import asyncio
import io
from pathlib import Path

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models.certificate import Certificate, CertificateTemplate
from app.domain.models.course import Course
from app.domain.models.user import User
from app.infrastructure.config.settings import settings
from app.infrastructure.storage.s3 import S3StorageService

logger = structlog.get_logger()

# A4 landscape dimensions in points (1 point = 1/72 inch)
PAGE_W, PAGE_H = 842, 595

# Platform brand colors
COLOR_TEAL = (0.176, 0.416, 0.310)  # #2D6A4F
COLOR_GOLD = (0.855, 0.647, 0.125)  # #DAA520
COLOR_DARK = (0.133, 0.133, 0.133)  # #222222
COLOR_GRAY = (0.400, 0.400, 0.400)  # #666666

# Font paths — DejaVu for full French accent support
_FONT_DIR = Path("/usr/share/fonts/truetype/dejavu")
_FONT_REGULAR = _FONT_DIR / "DejaVuSans.ttf"
_FONT_BOLD = _FONT_DIR / "DejaVuSans-Bold.ttf"


def _register_fonts() -> str:
    """Register DejaVu fonts with ReportLab. Returns the font family name."""
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    family = "DejaVu"
    if family not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont("DejaVu", str(_FONT_REGULAR)))
        pdfmetrics.registerFont(TTFont("DejaVu-Bold", str(_FONT_BOLD)))
    return family


def _render_pdf(
    certificate: Certificate,
    template: CertificateTemplate,
    course: Course,
    user: User,
    language: str,
) -> bytes:
    """Synchronous PDF rendering using ReportLab canvas. Returns PDF bytes."""
    from reportlab.pdfgen.canvas import Canvas

    _register_fonts()

    buf = io.BytesIO()
    c = Canvas(buf, pagesize=(PAGE_W, PAGE_H))
    c.setTitle("Certificate" if language == "en" else "Certificat")

    # ── Decorative border ──────────────────────────────────────
    margin = 20
    c.setStrokeColorRGB(*COLOR_TEAL)
    c.setLineWidth(3)
    c.roundRect(margin, margin, PAGE_W - 2 * margin, PAGE_H - 2 * margin, 10)

    # Inner border (gold)
    c.setStrokeColorRGB(*COLOR_GOLD)
    c.setLineWidth(1.5)
    c.roundRect(margin + 8, margin + 8, PAGE_W - 2 * (margin + 8), PAGE_H - 2 * (margin + 8), 8)

    # ── Corner decorations ─────────────────────────────────────
    c.setStrokeColorRGB(*COLOR_GOLD)
    c.setLineWidth(2)
    corners = [
        (margin + 15, PAGE_H - margin - 15),  # top-left
        (PAGE_W - margin - 15, PAGE_H - margin - 15),  # top-right
        (margin + 15, margin + 15),  # bottom-left
        (PAGE_W - margin - 15, margin + 15),  # bottom-right
    ]
    for cx, cy in corners:
        c.circle(cx, cy, 4, stroke=1, fill=0)

    # ── Platform name ──────────────────────────────────────────
    y = PAGE_H - 70
    c.setFont("DejaVu-Bold", 14)
    c.setFillColorRGB(*COLOR_TEAL)
    c.drawCentredString(PAGE_W / 2, y, "SIRA")

    # ── Title ──────────────────────────────────────────────────
    y -= 35
    c.setFont("DejaVu-Bold", 26)
    c.setFillColorRGB(*COLOR_TEAL)
    if language == "fr":
        c.drawCentredString(PAGE_W / 2, y, "CERTIFICAT DE REUSSITE")
    else:
        c.drawCentredString(PAGE_W / 2, y, "CERTIFICATE OF COMPLETION")

    # ── Subtitle ───────────────────────────────────────────────
    y -= 22
    c.setFont("DejaVu", 10)
    c.setFillColorRGB(*COLOR_GRAY)
    if language == "fr":
        c.drawCentredString(PAGE_W / 2, y, "Ce certificat est decerne a")
    else:
        c.drawCentredString(PAGE_W / 2, y, "This certificate is awarded to")

    # ── Learner name ───────────────────────────────────────────
    y -= 38
    c.setFont("DejaVu-Bold", 24)
    c.setFillColorRGB(*COLOR_DARK)
    learner_name = user.name or user.email or "Learner"
    c.drawCentredString(PAGE_W / 2, y, learner_name)

    # ── Decorative line under name ─────────────────────────────
    y -= 10
    c.setStrokeColorRGB(*COLOR_GOLD)
    c.setLineWidth(1)
    c.line(PAGE_W / 2 - 120, y, PAGE_W / 2 + 120, y)

    # ── Course completion text ─────────────────────────────────
    y -= 25
    c.setFont("DejaVu", 11)
    c.setFillColorRGB(*COLOR_GRAY)
    if language == "fr":
        c.drawCentredString(PAGE_W / 2, y, "Pour avoir complete avec succes le cours")
    else:
        c.drawCentredString(PAGE_W / 2, y, "For successfully completing the course")

    # ── Course title ───────────────────────────────────────────
    y -= 30
    c.setFont("DejaVu-Bold", 16)
    c.setFillColorRGB(*COLOR_TEAL)
    course_title = course.title_fr if language == "fr" else course.title_en
    # Truncate very long titles
    if len(course_title) > 60:
        course_title = course_title[:57] + "..."
    c.drawCentredString(PAGE_W / 2, y, course_title)

    # ── Score & date ───────────────────────────────────────────
    y -= 30
    c.setFont("DejaVu", 10)
    c.setFillColorRGB(*COLOR_DARK)
    score_text = f"Score: {certificate.average_score:.0f}%"
    date_str = certificate.completed_at.strftime("%d/%m/%Y") if certificate.completed_at else ""
    date_label = "Date" if language == "en" else "Date"
    info_text = f"{score_text}    |    {date_label}: {date_str}"
    c.drawCentredString(PAGE_W / 2, y, info_text)

    # ── Additional text from template ──────────────────────────
    additional = template.additional_text_fr if language == "fr" else template.additional_text_en
    if additional:
        y -= 22
        c.setFont("DejaVu", 9)
        c.setFillColorRGB(*COLOR_GRAY)
        if len(additional) > 100:
            additional = additional[:97] + "..."
        c.drawCentredString(PAGE_W / 2, y, additional)

    # ── Organization & Signatory (left side) ───────────────────
    y_bottom = 85
    if template.organization_name:
        c.setFont("DejaVu", 9)
        c.setFillColorRGB(*COLOR_GRAY)
        c.drawString(60, y_bottom + 40, template.organization_name)

    if template.signatory_name:
        c.setFont("DejaVu-Bold", 10)
        c.setFillColorRGB(*COLOR_DARK)
        c.drawString(60, y_bottom + 20, template.signatory_name)

    if template.signatory_title:
        c.setFont("DejaVu", 9)
        c.setFillColorRGB(*COLOR_GRAY)
        c.drawString(60, y_bottom + 5, template.signatory_title)

    # Signature line
    c.setStrokeColorRGB(*COLOR_GRAY)
    c.setLineWidth(0.5)
    c.line(60, y_bottom + 15, 250, y_bottom + 15)

    # ── QR code (right side) ───────────────────────────────────
    verification_url = f"{settings.frontend_url}/verify/{certificate.verification_code}"
    try:
        import qrcode

        qr = qrcode.QRCode(version=1, box_size=3, border=1)
        qr.add_data(verification_url)
        qr.make(fit=True)
        qr_img = qr.make_image(fill_color="black", back_color="white")

        qr_buf = io.BytesIO()
        qr_img.save(qr_buf, format="PNG")
        qr_buf.seek(0)

        from reportlab.lib.utils import ImageReader

        qr_size = 70
        c.drawImage(
            ImageReader(qr_buf),
            PAGE_W - 60 - qr_size,
            y_bottom - 5,
            width=qr_size,
            height=qr_size,
        )
    except Exception:
        logger.warning("QR code generation failed, skipping")

    # ── Verification code footer ───────────────────────────────
    c.setFont("DejaVu", 8)
    c.setFillColorRGB(*COLOR_GRAY)
    c.drawCentredString(PAGE_W / 2, margin + 12, f"Verification: {certificate.verification_code}")
    c.drawCentredString(PAGE_W / 2, margin + 2, verification_url)

    c.save()
    return buf.getvalue()


class CertificatePDFService:
    """Generates certificate PDFs and stores them in MinIO."""

    async def generate_pdf(
        self,
        certificate: Certificate,
        template: CertificateTemplate,
        course: Course,
        user: User,
        language: str = "fr",
    ) -> bytes:
        """Generate certificate PDF bytes. Runs ReportLab in a thread pool."""
        return await asyncio.to_thread(_render_pdf, certificate, template, course, user, language)

    async def generate_and_store(
        self,
        certificate: Certificate,
        template: CertificateTemplate,
        course: Course,
        user: User,
        db: AsyncSession,
        language: str = "fr",
    ) -> str:
        """Generate PDF, upload to MinIO, update certificate record.

        Returns the public URL of the stored PDF.
        """
        pdf_bytes = await self.generate_pdf(certificate, template, course, user, language)

        # Upload to MinIO
        storage = S3StorageService()
        key = f"certificates/{certificate.id}.pdf"
        url = await storage.upload_bytes(key, pdf_bytes, content_type="application/pdf")

        # Update certificate record
        certificate.pdf_url = url
        await db.commit()

        logger.info(
            "certificate_pdf_generated",
            certificate_id=str(certificate.id),
            size_bytes=len(pdf_bytes),
            url=url,
        )
        return url
