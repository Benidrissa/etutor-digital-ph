// The licence gate of the asset foundry (docs/story-mode-3d-assets.md §6).
//
// Same policy as story photos (#2681): CC0, public domain, CC BY and CC BY-SA
// only; NC, ND, store licences and anything unclear are refused. On top:
//   - a sticker (composited on the stage, next to the AI cast) takes no
//     share-alike licence, which would spread to what it is composited with;
//   - every entry names its author and the page its licence was read from;
//   - a model marked "noai" may be rendered but never restyled by an AI.
// render.mjs writes each verdict next to its render; postprocess.py publishes
// only renders that carry one, so these rules live in this file alone.

const PUBLIC = /^(CC0-1\.0|PDM)$/;
const BY = /^CC-BY-[1-4]\.0$/;
const BY_SA = /^CC-BY-SA-[1-4]\.0$/;

/** Whether a manifest entry may be rendered, and what it then requires. */
export function gate(entry) {
  const source = entry?.source ?? {};
  const licence = String(source.license ?? "").trim().toUpperCase().replace(/^CC0$/, "CC0-1.0");
  const refuse = (reason) => ({ ok: false, reason });
  if (!entry?.id || !/^[a-z0-9_]{1,60}$/.test(entry.id)) return refuse("id must be snake_case");
  if (!["sticker", "closeup"].includes(entry.kind)) return refuse(`unknown kind ${entry.kind}`);
  if (!licence) return refuse("no licence");
  if (/-NC|-ND|NONCOMMERCIAL|NODERIV/.test(licence)) return refuse(`${licence}: NC and ND are refused`);
  const isPublic = PUBLIC.test(licence);
  const isBy = BY.test(licence);
  const isBySa = BY_SA.test(licence);
  if (!isPublic && !isBy && !isBySa) return refuse(`${licence}: not an accepted licence`);
  if (isBySa && entry.kind === "sticker") return refuse(`${licence}: share-alike is close-up only, never a sticker`);
  if (!source.author) return refuse("no author");
  if (!source.page) return refuse("no source page to show where the licence was read");
  return {
    ok: true,
    licence,
    attributionRequired: !isPublic,
    aiRestyleAllowed: !source.noai && !isBySa,
  };
}
