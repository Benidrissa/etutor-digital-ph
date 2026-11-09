/**
 * "Image credits" (#2681): who made every picture the story shows — course
 * figures, open-licence photos and the drawings made with AI — with their
 * licence and source. Opened from the story's header and its end card.
 *
 * Built from the story document alone (no picture is loaded), so it opens
 * offline like the rest of a downloaded story.
 */

"use client";

import { useTranslations } from "next-intl";

import { text } from "@/lib/story-course/answer";
import type { MediaCredit, StoryCourse } from "@/lib/story-course/types";

import { CreditLine, StoryDialog } from "./look-closer";
import { EMOJI_FONTS, emojiDrawn, pictureFor, propLabel, sameOriginMedia } from "./props";

export interface CreditEntry {
  key: string;
  /** What the picture shows: a prop's name, or a figure's number. */
  label: string;
  emoji?: string;
  credit: MediaCredit;
}

function nonEmpty(value: unknown): string | undefined {
  if (typeof value === "number" && Number.isFinite(value)) return String(value);
  return typeof value === "string" && value.trim() ? value.trim() : undefined;
}

/**
 * Every credit the story needs: course figures first, then photos, then one
 * line for the drawings made with AI (characters, places and stickers).
 */
export function creditsFor(story: StoryCourse, lang: "fr" | "en"): CreditEntry[] {
  const entries: CreditEntry[] = [];
  const seen = new Set<string>();
  let drawn = false;

  for (const prop of story.props ?? []) {
    if (!prop?.id) continue;
    const media = story.art?.props?.[prop.id];
    if (sameOriginMedia(media?.sticker)) drawn = true;
    const picture = pictureFor(prop, media, lang);
    if (!picture || picture.via === "ai_drawing") continue;
    const key = `${picture.credit.kind}:${picture.src.split("?")[0]}`;
    if (seen.has(key)) continue;
    seen.add(key);
    entries.push({ key, label: propLabel(prop, lang, lang === "fr" ? "en" : "fr"), emoji: prop.emoji, credit: picture.credit });
  }

  // Figures shown by a `show` step (contract X4) carry their own attribution.
  for (const chapter of story.chapters ?? []) {
    for (const scene of chapter.scenes ?? []) {
      for (const step of scene.steps ?? []) {
        if (step.type !== "show" || step.visual !== "image") continue;
        const id = nonEmpty(step.params?.source_image_id);
        if (!id) continue;
        const key = `course:/api/v1/source-images/${id}/data`;
        if (seen.has(key)) continue;
        seen.add(key);
        const number = nonEmpty(step.params?.figure_number);
        const attribution = nonEmpty(step.params?.attribution);
        const parts = (from: string) => [from, number, attribution].filter(Boolean).join(" · ");
        entries.push({
          key,
          label: number ?? (step.caption ? text(step.caption, lang, lang === "fr" ? "en" : "fr") : id.slice(0, 8)),
          credit: { kind: "course", title: number, text: { en: parts("From the course"), fr: parts("Tiré du cours") } },
        });
      }
    }
  }

  const order: Record<MediaCredit["kind"], number> = { course: 0, web: 1, generated: 2 };
  entries.sort((a, b) => order[a.credit.kind] - order[b.credit.kind]);

  const art = story.art;
  if (
    drawn ||
    Object.values(art?.characters ?? {}).some((poses) => Object.values(poses ?? {}).some(Boolean)) ||
    Object.values(art?.places ?? {}).some(Boolean)
  ) {
    entries.push({
      key: "generated",
      label: "",
      credit: {
        kind: "generated",
        text: {
          en: "Characters, places and stickers: drawings made with AI",
          fr: "Personnages, lieux et autocollants : dessins faits par une IA",
        },
      },
    });
  }
  return entries;
}

export function CreditsSheet({
  entries,
  target,
  home,
  onClose,
}: {
  entries: CreditEntry[];
  target: string;
  home: string;
  onClose: () => void;
}) {
  const t = useTranslations("Story");
  return (
    <StoryDialog label={t("imageCredits")} onClose={onClose}>
      {(closeButton) => (
        <section data-testid="credits-sheet">
          <div className="-mx-3 flex min-h-9 items-center justify-between gap-2 rounded-t-[0.85rem] bg-[#1d2b4f] px-4 py-1 text-sm font-extrabold uppercase tracking-wide text-white">
            <h2>{t("imageCredits")}</h2>
            {closeButton}
          </div>
          <ul className="mt-2 divide-y divide-gray-100">
            {entries.map((entry) => (
              <li key={entry.key} className="flex gap-3 py-2">
                <span
                  aria-hidden="true"
                  className="w-6 shrink-0 text-center text-lg leading-6"
                  style={{ fontFamily: EMOJI_FONTS }}
                >
                  {entry.emoji && emojiDrawn(entry.emoji)
                    ? entry.emoji
                    : entry.credit.kind === "generated"
                      ? "🎨"
                      : entry.credit.kind === "course"
                        ? "📘"
                        : "📷"}
                </span>
                <span className="min-w-0">
                  {entry.label ? (
                    <span className="block text-sm font-semibold text-gray-900" lang={target}>
                      {entry.label}
                    </span>
                  ) : null}
                  <CreditLine credit={entry.credit} target={target} home={home} />
                </span>
              </li>
            ))}
          </ul>
        </section>
      )}
    </StoryDialog>
  );
}
