import type { SourceImageMeta } from '@/lib/api';

export const SOURCE_IMAGE_RE = /\{\{source_image:([0-9a-f-]{36})\}\}/g;

export type SourceImagePart =
  | { type: 'markdown'; text: string }
  | { type: 'source_image'; meta: SourceImageMeta };

export function splitWithSourceImageMarkers(
  text: string,
  imageMap: Map<string, SourceImageMeta>
): SourceImagePart[] {
  const parts: SourceImagePart[] = [];
  let lastIndex = 0;
  let match: RegExpExecArray | null;

  SOURCE_IMAGE_RE.lastIndex = 0;
  while ((match = SOURCE_IMAGE_RE.exec(text)) !== null) {
    if (match.index > lastIndex) {
      parts.push({ type: 'markdown', text: text.slice(lastIndex, match.index) });
    }
    const meta = imageMap.get(match[1]);
    if (meta) {
      parts.push({ type: 'source_image', meta });
    } else if (process.env.NODE_ENV !== 'production') {
      // Orphan marker: model cited an image whose ref was dropped (e.g. by the
      // max-5 cap during lesson generation). Skip it so the literal
      // {{source_image:…}} string never leaks into rendered text.
      console.debug('Dropping orphan source_image marker', match[1]);
    }
    lastIndex = SOURCE_IMAGE_RE.lastIndex;
  }
  if (lastIndex < text.length) {
    parts.push({ type: 'markdown', text: text.slice(lastIndex) });
  }
  return parts;
}
