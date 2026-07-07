/**
 * Markdown normalization helpers applied to AI-generated content before it is
 * handed to react-markdown / remark-gfm.
 *
 * AI-generated lessons and case studies frequently emit GFM tables directly
 * against the preceding text line, with no blank line between them, e.g.:
 *
 *   2) L'architecture ... les deux grandes parties :
 *   | Partie | Rôle | Source |
 *   |---|---|---|
 *
 * remark-gfm (micromark-extension-gfm-table) only recognizes a table when it is
 * preceded by a blank line — otherwise the whole block parses as a paragraph and
 * the pipes render literally. `normalizeMarkdown` inserts the missing blank line
 * so every table renders, without needing to regenerate stored content.
 */

const TABLE_ROW = /^\s*\|.*\|\s*$/;
const FENCE = /^\s*(```|~~~)/;

/**
 * Ensure a blank line precedes every GFM table block. Lines inside fenced code
 * blocks are left untouched so pipe-containing code is not disturbed. Idempotent:
 * already-spaced tables are unchanged.
 */
export function normalizeMarkdown(text: string): string {
  if (typeof text !== 'string' || text.length === 0) return text;

  const lines = text.split('\n');
  const out: string[] = [];
  let inFence = false;

  for (const line of lines) {
    if (FENCE.test(line)) inFence = !inFence;

    if (!inFence && TABLE_ROW.test(line)) {
      const prev = out.length ? out[out.length - 1] : '';
      if (prev.trim() !== '' && !TABLE_ROW.test(prev)) {
        out.push('');
      }
    }

    out.push(line);
  }

  return out.join('\n');
}
