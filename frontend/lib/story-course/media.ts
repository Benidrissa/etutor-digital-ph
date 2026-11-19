/**
 * The pictures a story takes from the course (#2709): the figures of its PDF
 * (`/api/v1/source-images/<id>/data`) and its lesson illustrations
 * (`/api/v1/images/<id>/data`, which may answer 302 to a CDN).
 *
 * Pure: the module download lists them from the story document alone, to warm
 * the service worker's caches on an explicit download, never on a plain read.
 */

import type { StoryCourse } from "./types";

const ID = /^[0-9a-f][0-9a-f-]{7,63}$/i;

/** A source figure is served in the lesson's languages only. */
export function figureLanguage(target: string, home: string): "fr" | "en" {
  if (target === "fr" || target === "en") return target;
  return home === "fr" ? "fr" : "en";
}

/** The learner asked to save data, or the link is 2G: no large or eager photos. */
export function savesData(): boolean {
  if (typeof navigator === "undefined") return false;
  const connection = (navigator as Navigator & {
    connection?: { saveData?: boolean; effectiveType?: string };
  }).connection;
  if (!connection) return false;
  return !!connection.saveData || connection.effectiveType === "slow-2g" || connection.effectiveType === "2g";
}

function idOf(value: unknown): string | undefined {
  return typeof value === "string" && ID.test(value.trim()) ? value.trim() : undefined;
}

/** The url of the picture a `show image` step (or a prop's figure) names, if any. */
export function figureUrl(
  figure: { source_image_id?: unknown; generated_image_id?: unknown; original?: unknown } | undefined,
  lang: "fr" | "en",
): string | undefined {
  const sourceId = idOf(figure?.source_image_id);
  if (sourceId) {
    // The localised variant only when asked for: it can be a smaller render (#2709).
    return `/api/v1/source-images/${sourceId}/data${figure?.original ? "" : `?lang=${lang}`}`;
  }
  const generatedId = idOf(figure?.generated_image_id);
  return generatedId ? `/api/v1/images/${generatedId}/data` : undefined;
}

/** The urls of the course figures and lesson illustrations a story shows, once each. */
export function storyFigureUrls(story: StoryCourse): string[] {
  const lang = figureLanguage(story.languages?.target ?? "", story.languages?.home ?? "");
  const urls = new Set<string>();
  const add = (
    figure: { source_image_id?: unknown; generated_image_id?: unknown; original?: unknown } | undefined,
  ) => {
    const url = figureUrl(figure, lang);
    if (url) urls.add(url);
  };
  for (const prop of story.props ?? []) {
    add(prop?.figure);
  }
  for (const chapter of story.chapters ?? []) {
    for (const scene of chapter.scenes ?? []) {
      for (const step of scene.steps ?? []) {
        if (step.type === "show" && step.visual === "image") {
          add(step.params);
        }
      }
    }
  }
  return [...urls];
}

/**
 * A file name made readable as a credit: no extension, underscores and hyphen
 * runs as spaces, cut at about 60 characters on a word boundary. Text that is
 * already a title is left as it is (apart from the cut).
 */
export function humanSource(value: string | undefined, limit = 60): string | undefined {
  if (!value) return undefined;
  let name = value.trim().replace(/\.(pdf|docx?|pptx?|epub|csv|txt)\b/gi, "");
  if (/[_]|-{2,}/.test(name) || /\.(pdf)$/i.test(value.trim())) name = name.replace(/[_]+|-{2,}/g, " ");
  name = name.replace(/\s+/g, " ").trim();
  if (name.length > limit) {
    const cut = name.slice(0, limit);
    const space = cut.lastIndexOf(" ");
    name = (space > limit / 2 ? cut.slice(0, space) : cut).replace(/[\s,;:.\-–—]+$/, "") + "…";
  }
  return name || undefined;
}

/** "Mindware__Tools….pdf, p.21": the file name made readable, the page kept. */
export function humanAttribution(value: string | undefined): string | undefined {
  if (!value) return undefined;
  const page = /(?:,\s*|\s)(p\.?\s*\d+(?:[-–]\d+)?)\s*$/i.exec(value);
  const title = humanSource(page ? value.slice(0, page.index) : value);
  return [title, page?.[1]].filter(Boolean).join(", ") || undefined;
}
