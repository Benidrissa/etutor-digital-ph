"""Tests for unreadable-image detection (#2540).

Each signal in ``assess_readability`` is high-precision by design: a false
positive silently deletes a real figure. These tests pin both the rejects
(blank, solid, random noise, undecodable bytes) and — just as importantly —
the keeps (sparse line-diagram, high-entropy smooth gradient).
"""

import io
import random

from PIL import Image, ImageDraw

from app.ai.rag.image_extractor import ExtractedImage, PDFImageExtractor
from app.ai.rag.image_quality import assess_readability


def _png(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _blank_white() -> bytes:
    return _png(Image.new("L", (256, 256), 255))


def _solid_color() -> bytes:
    return _png(Image.new("RGB", (300, 300), (123, 200, 50)))


def _random_noise() -> bytes:
    data = random.Random(0).randbytes(256 * 256)
    return _png(Image.frombytes("L", (256, 256), data))


def _sparse_diagram() -> bytes:
    """Mostly-white page with a few thin black lines — a legitimate figure."""
    img = Image.new("L", (256, 256), 255)
    draw = ImageDraw.Draw(img)
    draw.rectangle((40, 40, 120, 90), outline=0, width=2)
    draw.line((120, 65, 180, 65), fill=0, width=2)
    draw.rectangle((180, 40, 220, 90), outline=0, width=2)
    return _png(img)


def _smooth_gradient() -> bytes:
    """Left-to-right ramp: flat histogram (high entropy) but tiny neighbour diff."""
    row = bytes(range(256))
    data = row * 256
    return _png(Image.frombytes("L", (256, 256), data))


class TestAssessReadabilityRejects:
    def test_blank_white_rejected(self):
        readable, reason = assess_readability(_blank_white())
        assert readable is False
        assert reason and reason.startswith("blank")

    def test_solid_color_rejected(self):
        readable, reason = assess_readability(_solid_color())
        assert readable is False
        assert reason and reason.startswith("blank")

    def test_random_noise_rejected(self):
        readable, reason = assess_readability(_random_noise())
        assert readable is False
        assert reason and reason.startswith("noise")

    def test_undecodable_bytes_rejected(self):
        readable, reason = assess_readability(b"this is not an image")
        assert readable is False
        assert reason and reason.startswith("decode_failed")

    def test_truncated_png_rejected(self):
        truncated = _sparse_diagram()[:120]
        readable, reason = assess_readability(truncated)
        assert readable is False
        assert reason and reason.startswith("decode_failed")


class TestAssessReadabilityKeeps:
    def test_sparse_line_diagram_kept(self):
        # The critical non-regression: sparse diagrams look "almost blank" but
        # carry real information and must survive.
        readable, reason = assess_readability(_sparse_diagram())
        assert readable is True
        assert reason is None

    def test_high_entropy_smooth_gradient_kept(self):
        # Flat histogram trips the entropy gate, but the low neighbour-diff gate
        # (both required for "noise") keeps this readable.
        readable, reason = assess_readability(_smooth_gradient())
        assert readable is True
        assert reason is None


class TestFilterUnreadableIntegration:
    def _extracted(self, image_bytes: bytes, **kw) -> ExtractedImage:
        defaults = dict(
            image_bytes=image_bytes,
            width=256,
            height=256,
            original_format="png",
            file_size_bytes=len(image_bytes),
            page_number=1,
            figure_number=None,
            caption=None,
            attribution=None,
            image_type="unknown",
            surrounding_text="",
            chapter=None,
            section=None,
        )
        defaults.update(kw)
        return ExtractedImage(**defaults)

    def _extractor(self, tmp_path) -> PDFImageExtractor:
        return PDFImageExtractor(tmp_path)

    def test_filter_drops_unreadable_keeps_real(self, tmp_path):
        ext = self._extractor(tmp_path)
        images = [
            self._extracted(_blank_white(), page_number=1),
            self._extracted(_sparse_diagram(), page_number=2),
            self._extracted(_random_noise(), page_number=3),
        ]
        kept = ext._filter_unreadable(images, "generic")
        assert [img.page_number for img in kept] == [2]

    def test_filter_disabled_keeps_everything(self, tmp_path, monkeypatch):
        ext = self._extractor(tmp_path)

        class _S:
            enable_image_readability_filter = False

        monkeypatch.setattr("app.ai.rag.image_extractor.get_settings", lambda: _S())
        images = [
            self._extracted(_blank_white(), page_number=1),
            self._extracted(_sparse_diagram(), page_number=2),
        ]
        kept = ext._filter_unreadable(images, "generic")
        assert len(kept) == 2
