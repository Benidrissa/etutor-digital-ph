// @vitest-environment node
//
// Run in Node (not jsdom): jsdom does not expose WebCrypto's `crypto.subtle`,
// whereas Node — like a real browser's secure context — does, so this exercises
// the actual hashing path rather than the unavailable-fallback.
import { describe, it, expect } from "vitest";

import { sha256Hex } from "./file-hash";

// Known SHA-256 vector: the digest of the bytes "abc".
const ABC_SHA256 =
  "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad";

describe("sha256Hex", () => {
  it("returns the lowercase hex SHA-256 of a file's bytes", async () => {
    const file = new File(["abc"], "abc.pdf", { type: "application/pdf" });
    const hex = await sha256Hex(file);
    expect(hex).toBe(ABC_SHA256);
  });

  it("produces a 64-char hex digest for binary content", async () => {
    const file = new File([new Uint8Array([0, 1, 2, 255])], "bin.pdf");
    const hex = await sha256Hex(file);
    expect(hex).toMatch(/^[0-9a-f]{64}$/);
  });

  it("returns null (not throwing) when SubtleCrypto is unavailable", async () => {
    const original = globalThis.crypto;
    // Simulate a non-secure context where crypto.subtle is missing.
    Object.defineProperty(globalThis, "crypto", {
      value: {},
      configurable: true,
    });
    try {
      const hex = await sha256Hex(new File(["x"], "x.pdf"));
      expect(hex).toBeNull();
    } finally {
      Object.defineProperty(globalThis, "crypto", {
        value: original,
        configurable: true,
      });
    }
  });
});
