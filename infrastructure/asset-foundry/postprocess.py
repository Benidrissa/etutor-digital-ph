#!/usr/bin/env python3
"""Asset foundry, step 2: turn the renders into library files.

    python postprocess.py --manifest manifest.json --models <dir> --out <dir>

Reads ``<out>/raw/<id>.png`` and the licence verdict ``render.mjs`` wrote next
to it (``<id>.gate.json``: a render without a verdict is never published),
then writes into ``<out>``:

* ``<id>.webp``: a sticker trimmed to its silhouette, with a thick stroke in
  the stage's outline colour, at most 400 px on its long side; or a close-up,
  at most 400 px, plus ``<id>@960.webp`` for the large view;
* ``library.json``: one entry per published file, with its label, tags, sizes,
  licence, credit line (EN/FR) and provenance, ready to load into the library
  table (docs/story-mode-3d-assets.md §5.3);
* ``contact-sheet.png``: every published picture with its name, for review.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

#: Alpha at or below this is background (as story_art_service.ALPHA_THRESHOLD).
ALPHA_THRESHOLD = 16
#: PropPicture: ``src`` at most 400 px, ``src_large`` at most 960 px.
SMALL, LARGE = 400, 960
#: The stage's outline colour (O in backdrop.tsx) and the stroke, in render pixels.
OUTLINE = (59, 36, 24)
STROKE_PX = 13
WEBP_QUALITY = 82

LICENCE_LABELS = {"CC0-1.0": "CC0 1.0", "PDM": "public domain"}


def licence_label(code: str) -> str:
    """"CC-BY-SA-4.0" → "CC BY-SA 4.0" (as props.ts licenseLabel)."""
    if code in LICENCE_LABELS:
        return LICENCE_LABELS[code]
    parts = code.split("-")
    return f"CC {'-'.join(parts[1:-1])} {parts[-1]}" if code.startswith("CC-") else code


def credit(entry: dict, verdict: dict) -> dict[str, str]:
    """The credit line, in English and French (TASL for attribution licences)."""
    source = entry["source"]
    label = licence_label(verdict["licence"])
    site = source.get("site") or source.get("page", "")
    if not verdict.get("attributionRequired"):
        return {
            "en": f"3D model: {source['author']} ({label}), {site}",
            "fr": f"Modèle 3D : {source['author']} ({label}), {site}",
        }
    title = source.get("title") or entry["id"].replace("_", " ")
    return {
        "en": f"“{title}” by {source['author']}, {label}, {site}. Rendered by Sira: view, light and colours changed.",
        "fr": f"« {title} » de {source['author']}, {label}, {site}. Rendu par Sira : vue, lumière et couleurs modifiées.",
    }


def trim(image: Image.Image, margin: int = 0) -> Image.Image:
    mask = image.getchannel("A").point(lambda a: 255 if a > ALPHA_THRESHOLD else 0)
    box = mask.getbbox()
    if not box:
        raise ValueError("nothing drawn")
    left, top, right, bottom = box
    return image.crop(
        (max(0, left - margin), max(0, top - margin), min(image.width, right + margin), min(image.height, bottom + margin))
    )


def stroked(image: Image.Image) -> Image.Image:
    """A sticker: a solid stroke around the silhouette, under the picture."""
    mask = image.getchannel("A").point(lambda a: 255 if a > ALPHA_THRESHOLD else 0)
    stroke = mask.filter(ImageFilter.MaxFilter(STROKE_PX)).filter(ImageFilter.GaussianBlur(0.8))
    under = Image.new("RGBA", image.size, (*OUTLINE, 0))
    under.putalpha(stroke)
    return trim(Image.alpha_composite(under, image))


def fit(image: Image.Image, long_side: int) -> Image.Image:
    scale = long_side / max(image.size)
    if scale >= 1:
        return image
    return image.resize((round(image.width * scale), round(image.height * scale)), Image.LANCZOS)


def save_webp(image: Image.Image, path: Path) -> int:
    image.save(path, "WEBP", quality=WEBP_QUALITY, method=6)
    return path.stat().st_size


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def contact_sheet(pictures: list[tuple[str, Path]], path: Path, cell: int = 220) -> None:
    cols = 6
    rows = max(1, (len(pictures) + cols - 1) // cols)
    sheet = Image.new("RGB", (cols * cell, rows * (cell + 30)), (250, 244, 232))
    draw = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", 18)
    except OSError:
        font = ImageFont.load_default()
    for index, (name, file) in enumerate(pictures):
        x, y = (index % cols) * cell, (index // cols) * (cell + 30)
        thumb = Image.open(file).convert("RGBA")
        thumb.thumbnail((cell - 30, cell - 30), Image.LANCZOS)
        sheet.paste(thumb, (x + (cell - thumb.width) // 2, y + 10 + (cell - 20 - thumb.height)), thumb)
        draw.text((x + cell // 2, y + cell + 4), name, fill=OUTLINE, font=font, anchor="mt")
    sheet.save(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--models", required=True, help="folder the manifest's file paths are relative to")
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)

    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    out, models = Path(args.out), Path(args.models)
    raw = out / "raw"
    published: list[dict] = []
    pictures: list[tuple[str, Path]] = []
    skipped = 0
    for entry in manifest.get("entries", []):
        render, verdict_file = raw / f"{entry['id']}.png", raw / f"{entry['id']}.gate.json"
        if not render.exists() or not verdict_file.exists():
            skipped += 1
            continue
        verdict = json.loads(verdict_file.read_text(encoding="utf-8"))
        if not verdict.get("ok"):
            skipped += 1
            continue
        image = Image.open(render).convert("RGBA")
        files: dict[str, dict] = {}
        if entry["kind"] == "sticker":
            small = fit(stroked(image), SMALL)
            files["src"] = {"file": f"{entry['id']}.webp", "bytes": save_webp(small, out / f"{entry['id']}.webp")}
            size = small.size
        else:
            framed = trim(image, margin=24)
            large, small = fit(framed, LARGE), fit(framed, SMALL)
            files["src"] = {"file": f"{entry['id']}.webp", "bytes": save_webp(small, out / f"{entry['id']}.webp")}
            files["src_large"] = {
                "file": f"{entry['id']}@960.webp",
                "bytes": save_webp(large, out / f"{entry['id']}@960.webp"),
            }
            size = large.size
        model = models / entry["file"]
        published.append(
            {
                "id": entry["id"],
                "kind": entry["kind"],
                "label": entry.get("label", {}),
                "tags": entry.get("tags", []),
                "files": files,
                "width": size[0],
                "height": size[1],
                "licence": verdict["licence"],
                "attribution_required": verdict["attributionRequired"],
                "ai_restyle_allowed": verdict["aiRestyleAllowed"],
                "credit": credit(entry, verdict),
                "source": entry["source"],
                "model_sha256": sha256(model) if model.exists() else None,
                "library_version": manifest.get("library_version", 1),
            }
        )
        pictures.append((entry["id"], out / files["src"]["file"]))
        print(f"{entry['id']:24} {entry['kind']:8} {size[0]}x{size[1]}  {files['src']['bytes'] / 1024:.1f} KB")

    library = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "library_version": manifest.get("library_version", 1),
        "entries": published,
    }
    (out / "library.json").write_text(json.dumps(library, ensure_ascii=False, indent=1), encoding="utf-8")
    if pictures:
        contact_sheet(pictures, out / "contact-sheet.png")
    print(f"{len(published)} published, {skipped} without an accepted render; see {out / 'library.json'}")
    return 0 if published else 1


if __name__ == "__main__":
    sys.exit(main())
