#!/usr/bin/env python3
"""Fetch CC0 models for the shared story library from Poly Pizza (#2714).

Reads ``wishlist.json``; for each item searches Poly Pizza, keeps the first
result that is **CC0 1.0 and uploaded by an allowed author** (Quaternius or
Kenney, whose own sites state CC0, docs/story-mode-3d-assets.md section 12),
then **re-reads the model's own page** and refuses it unless the page itself
says ``Licence: CC0 1.0`` and names that author. It downloads the GLB, records
its sha256, and writes ``<out>/models/<id>.glb`` and ``<out>/manifest.json`` in
the format ``render.mjs`` reads.

Nothing here calls a paid service. Poly Pizza's pages are public. Be polite:
one request every ``--delay`` seconds.

    python3 fetch_poly_pizza.py --out work            # wishlist.json -> work/
    python3 fetch_poly_pizza.py --out work --only bucket,chair
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).parent
ALLOWED_AUTHORS = {"quaternius": "Quaternius", "kenney": "Kenney"}
LICENCE = "CC0 1.0"
#: A title with one of these words is never a generic decor prop.
REFUSED_WORDS = {
    "enemy", "zombie", "gun", "sword", "blaster", "weapon", "monster", "skeleton", "skull",
    "demon", "bomb", "grenade", "exploding", "ghost", "sci", "alien", "robot", "dragon",
    "tank", "rifle", "pistol", "axe", "knife", "dagger", "bow", "arrow", "coffin", "grave",
    "wizard", "witch", "orc", "goblin", "dead", "blood", "bone", "crossbow", "missile",
}
UA = "sira-asset-foundry/0.1 (CC0 curation; contact via the project repository)"
STATE = re.compile(r"__SERVER_APP_STATE__\s*=\s*(\{.*?\})\s*</script>", re.S)


def get(url: str, *, binary: bool = False):
    request = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(request, timeout=40) as response:  # noqa: S310
        data = response.read()
    return data if binary else data.decode("utf-8", "replace")


def state(html: str) -> dict:
    found = STATE.search(html)
    if not found:
        raise ValueError("no page state")
    return json.loads(found.group(1))


def words(text: str) -> list[str]:
    return [w for w in re.split(r"[^a-z]+", text.lower()) if w]


def singular(word: str) -> str:
    return word[:-1] if word.endswith("s") and len(word) > 3 else word


def title_fits(title: str, term: str) -> bool:
    got = {singular(w) for w in words(title)}
    if got & REFUSED_WORDS:
        return False
    return all(singular(w) in got for w in words(term))


def pick(term: str, results: list[dict]) -> dict | None:
    for result in results:
        creator = str((result.get("creator") or {}).get("username") or "").lower()
        if creator in ALLOWED_AUTHORS and result.get("licence") == LICENCE:
            if title_fits(str(result.get("title") or ""), term):
                return result
    return None


def verify(public_id: str) -> dict:
    """The model page's own facts; raises unless it says CC0 1.0 and an allowed author."""
    model = state(get(f"https://poly.pizza/m/{urllib.parse.quote(public_id)}"))["initialData"][
        "model"
    ]
    creator = str((model.get("Creator") or {}).get("Username") or "")
    if model.get("Licence") != LICENCE or creator.lower() not in ALLOWED_AUTHORS:
        raise ValueError(f"page says {model.get('Licence')!r} by {creator!r}")
    if model.get("Visibility") != "Public":
        raise ValueError("model is not public")
    return model


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", required=True)
    parser.add_argument("--wishlist", default=str(HERE / "wishlist.json"))
    parser.add_argument("--only", default="", help="comma-separated ids")
    parser.add_argument("--delay", type=float, default=0.6)
    args = parser.parse_args()
    out = Path(args.out)
    (out / "models").mkdir(parents=True, exist_ok=True)
    only = {s for s in args.only.split(",") if s}
    items = json.loads(Path(args.wishlist).read_text(encoding="utf-8"))["items"]
    entries, missing = [], []
    for slug, label_en, label_fr, term, tags in items:
        if only and slug not in only:
            continue
        try:
            time.sleep(args.delay)
            results = state(get("https://poly.pizza/search/" + urllib.parse.quote(term)))[
                "initialData"
            ]["result"]
            chosen = pick(term, results)
            if chosen is None:
                missing.append(f"{slug}: no CC0 Quaternius/Kenney result for {term!r}")
                continue
            time.sleep(args.delay)
            model = verify(chosen["publicID"])
            glb = get(f"https://static.poly.pizza/{model['ResourceID']}.glb", binary=True)
        except Exception as exc:  # noqa: BLE001
            missing.append(f"{slug}: {exc}")
            continue
        (out / "models" / f"{slug}.glb").write_bytes(glb)
        author = ALLOWED_AUTHORS[str(model["Creator"]["Username"]).lower()]
        entries.append(
            {
                "id": slug,
                "kind": "sticker",
                "file": f"models/{slug}.glb",
                "label": {"en": label_en, "fr": label_fr},
                "tags": tags,
                "source": {
                    "author": author,
                    "license": "CC0-1.0",
                    "page": f"https://poly.pizza/m/{model['PublicID']}",
                    "site": "Poly Pizza",
                    "title": model["Title"],
                    "sha256_original": hashlib.sha256(glb).hexdigest(),
                    "licence_read": "Poly Pizza model page: Licence CC0 1.0, creator " + author,
                },
            }
        )
        print(f"ok {slug}: {model['Title']!r} by {author} ({chosen['publicID']})")
    (out / "manifest.json").write_text(
        json.dumps({"library_version": 1, "entries": entries}, indent=2, ensure_ascii=False)
        + "\n",
        encoding="utf-8",
    )
    for line in missing:
        print("missing", line, file=sys.stderr)
    print(f"{len(entries)} fetched, {len(missing)} missing")
    return 0


if __name__ == "__main__":
    sys.exit(main())
