"""Readability detection for images extracted from course PDFs.

Drops images that carry no legible information *before* they are persisted as
``source_images`` and linked to generated content. The dimension/byte-size
floors in ``image_extractor`` only catch tiny images; an image can clear those
and still be a solid fill, random-decode garbage, or a truncated stream.

Three rejection signals, each tuned to be high-precision (a false positive here
silently deletes a real figure, so the bar is "obviously unreadable"):

* **decode-fail / truncated** — bytes that don't fully decode to pixels.
* **blank / near-uniform** — near-zero luminance spread *and* a near-1.0
  single-value fraction. Deliberately conservative so sparse line-diagrams and
  flowcharts (mostly-white background, thin ink) are KEPT — those measure a
  luminance stddev well above the blank floor.
* **random-noise garbage** — a near-flat 256-bin histogram (high entropy)
  *and* high difference between adjacent pixels (no smooth regions). Botched
  CMYK/SMask decodes look like colour static; natural photos and diagrams fail
  at least one of the two conditions, so both are required to reject.
"""

import io

import structlog

logger = structlog.get_logger(__name__)

# --- Blank / near-uniform -------------------------------------------------
# A solid fill has stddev ~0. A single thin diagonal line on a white page
# measures a luminance stddev around 16 after downscale; we reject only well
# below that. Both conditions must hold, so a low-stddev image with genuine
# (if faint) structure — which spreads the histogram below the dominant
# threshold — is kept.
BLANK_STDDEV_MAX = 4.0
# Fraction of pixels sharing the single most common luminance value. A solid
# fill approaches 1.0; bilinear downscale of any real ink anti-aliases edges
# and spreads the histogram below this, so even very sparse diagrams stay under.
BLANK_DOMINANT_FRACTION_MIN = 0.999

# --- Random-noise garbage -------------------------------------------------
# Shannon entropy of the 8-bit luminance histogram (max 8.0). Uniform noise
# approaches 8.0; detailed photos rarely exceed ~7.5 and, when they do, retain
# smooth regions (low neighbour diff) that the second gate catches.
NOISE_ENTROPY_MIN = 7.5
# Mean absolute difference between horizontally-adjacent pixels (0-255). Pure
# uniform noise sits near 85 (≈ 1/3 of the range); photos and diagrams stay
# well below 55 thanks to smooth gradients and flat backgrounds.
NOISE_NEIGHBOR_DIFF_MIN = 55.0

# Downscale longest side to this before computing statistics — keeps the cost
# roughly constant regardless of source resolution. Large enough to preserve
# the signal each gate measures.
ANALYSIS_MAX_DIM = 256


def _load_gray(image_bytes: bytes):
    """Decode ``image_bytes`` to a downscaled 8-bit grayscale PIL image.

    ``img.load()`` forces a full decode so truncated/partial streams raise here
    rather than later. Raises on any decode failure (caller treats as
    unreadable).
    """
    from PIL import Image

    img = Image.open(io.BytesIO(image_bytes))
    img.load()  # force full decode; truncated streams fail here
    img = img.convert("L")

    longest = max(img.size)
    if longest > ANALYSIS_MAX_DIM:
        ratio = ANALYSIS_MAX_DIM / longest
        img = img.resize(
            (max(1, int(img.width * ratio)), max(1, int(img.height * ratio))),
            Image.BILINEAR,
        )
    return img


def assess_readability(image_bytes: bytes) -> tuple[bool, str | None]:
    """Return ``(is_readable, reason)`` for a candidate image.

    ``reason`` is ``None`` when readable, otherwise a short diagnostic string
    (with the measured metrics) for logging. The check never raises — a decode
    failure is itself an "unreadable" verdict.
    """
    from PIL import ImageChops, ImageStat

    try:
        img = _load_gray(image_bytes)
    except Exception as exc:
        return False, f"decode_failed: {type(exc).__name__}: {exc}"

    if img.width < 2 or img.height < 2:
        return False, f"degenerate_dimensions: {img.width}x{img.height}"

    stat = ImageStat.Stat(img)
    stddev = stat.stddev[0]

    hist = img.histogram()
    total = sum(hist) or 1
    dominant = max(hist) / total

    # Blank / near-uniform: flat luminance AND one value dominating.
    if stddev <= BLANK_STDDEV_MAX and dominant >= BLANK_DOMINANT_FRACTION_MIN:
        return False, f"blank(stddev={stddev:.2f},dominant={dominant:.4f})"

    # Random-noise garbage: flat histogram AND no smooth regions. Both gates
    # required, so a busy-but-real photo (high entropy, smooth gradients) and a
    # high-contrast diagram (low entropy) both survive.
    entropy = img.entropy()
    if entropy >= NOISE_ENTROPY_MIN:
        left = img.crop((0, 0, img.width - 1, img.height))
        right = img.crop((1, 0, img.width, img.height))
        neighbor_diff = ImageStat.Stat(ImageChops.difference(left, right)).mean[0]
        if neighbor_diff >= NOISE_NEIGHBOR_DIFF_MIN:
            return False, f"noise(entropy={entropy:.2f},neighbor={neighbor_diff:.1f})"

    return True, None
