// SHA-256 hashing of files, computed in the browser via the Web Crypto API.
//
// Used to pre-check whether a PDF source is already indexed on the server
// before uploading it: the client hashes the file locally and sends only the
// digest, so an already-indexed source is reused with zero file transfer — a
// meaningful saving on the platform's 2G/3G target networks.

/**
 * Compute the lowercase hex SHA-256 digest of a file.
 *
 * Returns `null` (rather than throwing) when the Web Crypto SubtleCrypto API is
 * unavailable — e.g. a non-secure (HTTP) context — so callers can transparently
 * fall back to a normal upload.
 */
export async function sha256Hex(file: File): Promise<string | null> {
  if (!globalThis.crypto?.subtle) return null;
  try {
    const buf = await crypto.subtle.digest("SHA-256", await file.arrayBuffer());
    return Array.from(new Uint8Array(buf))
      .map((b) => b.toString(16).padStart(2, "0"))
      .join("");
  } catch {
    return null;
  }
}
