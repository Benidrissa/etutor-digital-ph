"""Image model ids (#2689), in one place for the image provider and the admin setting.

No imports: the platform defaults read it at import time.
"""

from __future__ import annotations

#: OpenAI's current image model: the ``ai-model-image`` default, the fallback of
#: every other backend, and the route of edits and transparent renders.
#: ``gpt-image-1`` was shut down on 2026-10-23; ``gpt-image-2.6-sunburst`` is the
#: deprecations page's recommended successor, with no announced shutdown date.
OPENAI_IMAGE_MODEL = "gpt-image-2.6-sunburst"

#: What an admin may pick for ``ai-model-image``.
IMAGE_MODEL_OPTIONS = (
    OPENAI_IMAGE_MODEL,
    "gpt-image-2.6-flare",
    "gpt-image-2.5-sunburst",
    "gemini-2.5-flash-image",
)
