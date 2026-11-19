# Asset foundry

Turns free 3D models into story-mode pictures, so the AI does not have to draw every object:

- **Stickers:** everyday props in the stage's cartoon style.
- **Close-ups:** "Look closely" renders of educational objects.

The plan, the license policy and the examples are in [docs/story-mode-3d-assets.md](../../docs/story-mode-3d-assets.md).

**Status: starting point.** The pipeline runs end to end on the example manifest. Its output is loaded into the app by `backend/scripts/import_story_library.py` (doc §13). It runs on an operator's machine or in CI, never on the VPS or in the learner's browser.

## Pipeline

```
manifest.json ─► render.mjs ─────────────────────► postprocess.py ──────────────────────► out/
                 licence gate (licences.mjs)        trim, sticker stroke, WebP             <id>.webp (≤ 400 px)
                 toon or close-up render            credit line (EN/FR), provenance        <id>@960.webp (close-ups)
                 headless Chromium, no GPU          only renders with an accepted verdict  library.json, contact-sheet.png
```

1. **`render.mjs`** checks each entry against the license gate, then renders the accepted ones with three.js in headless Chromium.
   - **`sticker`:** toon shading in three bands, colours mapped to the house palette (by material name first: `woodBark` becomes wood, `leafsGreen` becomes leaf), and a thin inner outline in the stage colour `#3b2418`.
   - **`closeup`:** soft realistic light. It can isolate named parts of a model (`nodes`), such as the heart in an anatomy model.
   - Next to each PNG it writes the gate verdict (`<id>.gate.json`). A refused entry is never rendered.
2. **`postprocess.py`** works only on renders that carry an accepted verdict.
   - **Stickers:** trimmed, given a thick silhouette stroke, at most 400 px.
   - **Close-ups:** 400 px and 960 px versions (`PropPicture.src` / `src_large`).
   - **`library.json`:** label, tags, sizes, license, credit line (EN/FR), provenance and the model file's sha256.
   - **`contact-sheet.png`:** for review.

## License gate (`licences.mjs`)

Same policy as story photos (#2681), plus two rules for 3D:

| License | Sticker | Close-up | AI restyle |
|---|---|---|---|
| CC0, public domain | ✅ | ✅ | ✅ |
| CC BY | ✅ credited | ✅ credited | ✅ unless `noai` |
| CC BY-SA | ❌ (share-alike would spread to the stage) | ✅ credited | ❌ |
| NC, ND, store and unknown licenses | ❌ | ❌ | ❌ |

Every entry must also name its `author` and the `page` its license was read from. Run the gate tests with `npm test` (`node --test`).

Each source has its own terms on top of the license (doc §3 and §12):
- **Poly Haven API:** free for any use, but it requires a credit to Poly Haven and a unique User-Agent. Set `"credit_required": true` on its entries.
- **Sketchfab:** each download needs a signed-in Sketchfab user, so the operator downloads curated models with their own account. Credits name the author, the license, the model link and Sketchfab. Prefer "Human Created" models, and set `"noai": true` on any model tagged NoAI.
- **ambientCG:** download once; never depend on its API at run time.

## Manifest

```jsonc
{
  "library_version": 1,
  "entries": [
    {
      "id": "frog",                       // snake_case, unique
      "kind": "sticker",                  // or "closeup"
      "file": "path/to/frog.glb",         // relative to --models
      "yaw": 0.6,                         // optional turn, in radians (stickers default to a 3/4 view)
      "palette": true,                    // stickers: map colours to the house palette (default true)
      "nodes": ["heart"],                 // close-ups: render only these named nodes
      "colors": {"heart": "#a8322c"},     // close-ups: colour per node
      "label": {"en": "a frog", "fr": "une grenouille"},
      "tags": ["frog", "amphibian"],
      "source": {
        "author": "Quaternius",
        "license": "CC0-1.0",             // CC0-1.0 | PDM | CC-BY-x.0 | CC-BY-SA-x.0
        "page": "https://…",              // where the license was read
        "site": "Poly Pizza",             // shown in the credit line
        "title": "…",                     // CC BY: the work's title, for the credit
        "noai": false,                    // true: never send it to an AI restyle (Sketchfab NoAI)
        "credit_required": false          // true: credit even a CC0 asset (Poly Haven API terms)
      }
    }
  ]
}
```

`manifest.example.json` holds the proof-of-concept entries:
- 12 CC0 stickers (Quaternius and Kenney);
- 2 CC BY 4.0 anatomy close-ups;
- 1 non-commercial entry, there on purpose so the gate refuses it.

Its files come from **unofficial npm mirrors** (`@netforge/asset-library-files`, `open-anatomy-3d`), because the original sites were unreachable when it was made. Use it for trials only. Production entries must point to files fetched from the original sites, with the page their license was read from.

## Run it

Needs Node 20+, Python 3.10+ with Pillow, and Chromium for Playwright.

```sh
cd infrastructure/asset-foundry
npm install                      # three.js, Playwright and the two mirror packages
npx playwright install chromium  # skip if a Playwright browser is already installed
pip install -r requirements.txt

npm run render                   # node render.mjs --manifest manifest.example.json --models node_modules --out out
npm run postprocess              # python3 postprocess.py … --out out
npm test                         # license gate tests
```

If Playwright and its browser are already installed elsewhere, point the script at that copy instead of installing a second one:

```sh
PLAYWRIGHT_MODULE=/path/to/node_modules/playwright node render.mjs …
```

Output goes to `out/` (git-ignored). A run of the example takes a few seconds:
- **Stickers:** 20–250 ms each, 5–17 KB.
- **Close-ups:** about 1.5 s each.

## Next steps

See the doc, §8.

1. **Phase 0:** rank the props the stories ask for, with `backend/scripts/story_prop_inventory.py`. It can also run from the *Generate Module Story* workflow, mode `props`. Use the result to choose the first ~150 manifest entries.
2. **Phase A:** the backend side is built (doc §13). Copy this folder's `out/` into the backend container and import it with `python scripts/import_story_library.py <folder> --dry-run`, then again without `--dry-run`. Stories then serve the matching stickers and close-ups ahead of the AI stickers (#2684).

## The shared library (#2714)

`library/manifest.json` is the versioned manifest of the generic CC0 decor props every stack ships; its output is committed in `backend/app/data/story_library` and imported automatically at API start (docs section 14).

```sh
# 1. fetch the models of wishlist.json; each is re-verified on its Poly Pizza page
python3 fetch_poly_pizza.py --out work            # writes work/models/*.glb and work/manifest.json
# 2. render and post-process (needs `npm install` and Pillow, as above)
node render.mjs --manifest work/manifest.json --models work --out work/out
python3 postprocess.py --manifest work/manifest.json --models work --out work/out
# 3. review work/out/contact-sheet.png, copy the kept entries and their WebP into
#    backend/app/data/story_library, merge library/manifest.json, bump library_version
```

`fetch_poly_pizza.py` keeps only models that Poly Pizza's own page says are `Licence: CC0 1.0` and uploaded by Quaternius or Kenney, and records each model's page and sha256. Review every render: some search hits are wrong (a toy, a different object), so entries are curated by eye before they are committed.
