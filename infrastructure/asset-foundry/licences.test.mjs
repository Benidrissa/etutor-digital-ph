// node --test: the licence gate (docs/story-mode-3d-assets.md §6).
import assert from "node:assert/strict";
import { test } from "node:test";

import { gate } from "./licences.mjs";

const entry = (kind, license, extra = {}) => ({
  id: "thing",
  kind,
  source: { author: "Someone", page: "https://example.org/thing", license, ...extra },
});

test("public domain and CC BY pass for both kinds", () => {
  for (const kind of ["sticker", "closeup"]) {
    for (const license of ["CC0-1.0", "CC0", "PDM", "CC-BY-3.0", "CC-BY-4.0"]) {
      assert.equal(gate(entry(kind, license)).ok, true, `${kind} ${license}`);
    }
  }
});

test("attribution is required for CC BY only", () => {
  assert.equal(gate(entry("sticker", "CC0-1.0")).attributionRequired, false);
  assert.equal(gate(entry("sticker", "CC-BY-4.0")).attributionRequired, true);
});

test("share-alike is for close-ups only, and never restyled by an AI", () => {
  assert.equal(gate(entry("sticker", "CC-BY-SA-4.0")).ok, false);
  const closeup = gate(entry("closeup", "CC-BY-SA-4.0"));
  assert.equal(closeup.ok, true);
  assert.equal(closeup.aiRestyleAllowed, false);
});

test("NC, ND, store and unknown licences are refused", () => {
  for (const license of ["CC-BY-NC-4.0", "CC-BY-NC-SA-4.0", "CC-BY-ND-4.0", "Standard", "Royalty Free", "", undefined]) {
    assert.equal(gate(entry("closeup", license)).ok, false, String(license));
  }
});

test("a model marked noai is rendered but not restyled", () => {
  const verdict = gate(entry("sticker", "CC-BY-4.0", { noai: true }));
  assert.equal(verdict.ok, true);
  assert.equal(verdict.aiRestyleAllowed, false);
});

test("provenance and shape are required", () => {
  assert.equal(gate({ ...entry("sticker", "CC0-1.0"), source: { license: "CC0-1.0", page: "x" } }).ok, false);
  assert.equal(gate({ ...entry("sticker", "CC0-1.0"), source: { license: "CC0-1.0", author: "x" } }).ok, false);
  assert.equal(gate({ ...entry("sticker", "CC0-1.0"), id: "Bad Id" }).ok, false);
  assert.equal(gate(entry("poster", "CC0-1.0")).ok, false);
});
