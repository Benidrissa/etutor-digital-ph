/**
 * "Look closely" (#2681): the real thing a story talks about — a course
 * figure, a photo, or its drawing — with its caption and its credit.
 *
 * Two variants: a step of the story (`show` with visual "prop"), drawn in the
 * stage's picture panel; and an overlay the learner opens by tapping a prop
 * on stage, a dialog that closes with Esc and gives the focus back.
 *
 * The picture box takes its shape from the picture's size before it loads,
 * so nothing jumps. A picture that fails falls back to its small size, then
 * to the prop's drawing, then to a name card. With data saving on, the photo
 * waits for a tap that says how big it is.
 */

"use client";

import { X } from "lucide-react";
import { useTranslations } from "next-intl";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";

import { text } from "@/lib/story-course/answer";
import { useInertBackground } from "@/lib/hooks/use-inert-background";
import type { MediaCredit, Prop, PropPicture, TextObject } from "@/lib/story-course/types";

import { EMOJI_FONTS, emojiDrawn, licenseLabel, propLabel, sameOriginMedia, savesData } from "./props";

interface LookCloserProps {
  prop: Prop;
  picture?: PropPicture;
  /** The prop's sticker, shown large when the picture cannot be. */
  stickerUrl?: string;
  /** The step's own caption, before the picture's. */
  caption?: TextObject;
  target: string;
  home: string;
  bilingual: boolean;
  variant: "step" | "overlay";
  headingLevel?: 3 | 4;
  /** Overlay only: closes it (Esc, the close button, a tap outside). */
  onClose?: () => void;
}

/** What the box shows, in fallback order. */
type Stage = "full" | "small" | "sticker" | "name";

const TEAL = "#0f766e";

function safeLink(url: string | undefined): string | undefined {
  if (!url) return undefined;
  try {
    const parsed = new URL(url);
    return parsed.protocol === "https:" ? parsed.toString() : undefined;
  } catch {
    return undefined;
  }
}

/** A picture's credit: the full line, then its licence and source as links. */
export function CreditLine({ credit, target, home }: { credit: MediaCredit; target: string; home: string }) {
  const t = useTranslations("Story");
  const line =
    text(credit.text, target, home) ||
    (credit.kind === "generated" ? t("creditDrawing") : credit.kind === "course" ? t("creditCourse") : "");
  const licenseUrl = safeLink(credit.license_url);
  const pageUrl = safeLink(credit.page_url);
  const license = licenseLabel(credit.license) ?? (credit.license ? t("publicDomain") : undefined);
  return (
    <p className="text-xs leading-snug text-gray-600" data-credit={credit.kind}>
      {line}
      {licenseUrl && license ? (
        <>
          {" · "}
          <a href={licenseUrl} target="_blank" rel="noopener noreferrer" className="underline">
            {license}
          </a>
        </>
      ) : null}
      {pageUrl ? (
        <>
          {" · "}
          <a href={pageUrl} target="_blank" rel="noopener noreferrer" className="underline">
            {t("creditSource")}
          </a>
        </>
      ) : null}
    </p>
  );
}

function LookCloserBody({
  prop,
  picture,
  stickerUrl,
  caption,
  target,
  home,
  bilingual,
  headingLevel = 3,
  closeButton,
}: Omit<LookCloserProps, "variant" | "onClose"> & { closeButton?: ReactNode }) {
  const t = useTranslations("Story");
  const sticker = sameOriginMedia(stickerUrl);
  const isDrawing = picture?.via === "ai_drawing";
  // The large picture only on a wide screen with no data saving: on a phone
  // the small one (the one fetched ahead) fills the box, and a srcset would
  // make a dense screen download the large one on 3G (#2688).
  const [wide] = useState(
    () =>
      typeof window !== "undefined" &&
      typeof window.matchMedia === "function" &&
      window.matchMedia("(min-width: 640px)").matches &&
      !savesData(),
  );
  const first: Stage = picture ? (picture.src_large && wide ? "full" : "small") : sticker ? "sticker" : "name";
  const [stage, setStage] = useState<Stage>(first);
  // With data saving on, a photo waits for the learner to ask for it.
  const [asked, setAsked] = useState(() => !picture || isDrawing || !savesData());

  const fail = () =>
    setStage((now) => {
      if (now === "full") return "small";
      if (now === "small" && sticker && sticker !== picture?.src) return "sticker";
      return "name";
    });

  const label = propLabel(prop, target, home);
  const homeLabel = text(prop.label, home, target);
  const shownCaption = caption ?? picture?.caption;
  const captionText = shownCaption ? text(shownCaption, target, home) : "";
  const captionHome = shownCaption ? text(shownCaption, home, target) : "";
  const Heading = headingLevel === 3 ? "h3" : "h4";
  const showsPicture = picture && (stage === "full" || stage === "small");
  const width = showsPicture ? picture.width : 1;
  const height = showsPicture ? picture.height : 1;
  // Its size, when the server says it: a course figure's is not known, and
  // its width and height are placeholders (#2688).
  const kb = picture?.bytes ? Math.max(1, Math.round(picture.bytes / 1024)) : undefined;

  return (
    <figure className="m-0" data-step-panel="look" data-look={stage}>
      <div
        className="-mx-3 flex min-h-9 items-center justify-between gap-2 rounded-t-[0.85rem] px-4 py-1 text-sm font-extrabold uppercase tracking-wide text-white"
        style={{ background: TEAL }}
      >
        <span>{t("lookCloser")}</span>
        {closeButton}
      </div>
      <Heading className="mt-2 text-lg font-extrabold leading-tight text-[#1d2b4f]" lang={target}>
        {label}
        {bilingual && homeLabel && homeLabel !== label ? (
          <span className="ml-2 text-base font-semibold italic text-gray-600" lang={home}>
            {homeLabel}
          </span>
        ) : null}
      </Heading>

      <div className="mt-2">
        {showsPicture && !asked ? (
          <button
            type="button"
            onClick={() => setAsked(true)}
            className="flex min-h-11 w-full items-center justify-center rounded-lg border-2 border-dashed border-teal-600 bg-teal-50 px-3 text-sm font-semibold text-teal-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-600"
            style={{ aspectRatio: `${width} / ${height}`, maxHeight: "16rem" }}
          >
            {kb ? t("loadPhoto", { kb }) : t("loadPhotoUnsized")}
          </button>
        ) : showsPicture ? (
          <div
            className="mx-auto overflow-hidden rounded-lg bg-gray-100"
            style={{ aspectRatio: `${width} / ${height}`, maxHeight: "min(22rem, 55vh)", maxWidth: "100%" }}
          >
            {/* eslint-disable-next-line @next/next/no-img-element -- same-origin story media with its own sizes */}
            <img
              key={stage}
              src={picture.src}
              srcSet={stage === "full" && picture.src_large ? `${picture.src} 400w, ${picture.src_large} 960w` : undefined}
              sizes={stage === "full" && picture.src_large ? "390px" : undefined}
              alt={text(picture.alt, target, home) || label}
              lang={target}
              className="h-full w-full object-contain"
              onError={fail}
            />
          </div>
        ) : stage === "sticker" && sticker ? (
          // eslint-disable-next-line @next/next/no-img-element -- the prop's same-origin sticker
          <img
            src={sticker}
            alt={label}
            lang={target}
            className="mx-auto block h-40 w-auto max-w-full object-contain"
            onError={() => setStage("name")}
          />
        ) : (
          <div className="flex flex-col items-center justify-center gap-1 rounded-lg bg-[#fff8db] px-3 py-5 text-center">
            {prop.emoji && emojiDrawn(prop.emoji) ? (
              <span className="text-5xl leading-none" style={{ fontFamily: EMOJI_FONTS }} aria-hidden="true">
                {prop.emoji}
              </span>
            ) : null}
            <span className="text-base font-extrabold text-[#1d2b4f]" lang={target}>
              {label}
            </span>
          </div>
        )}
      </div>

      {captionText || (stage !== "name" && picture) ? (
        <figcaption className="mt-2 space-y-1 pb-1">
          {captionText ? (
            <p className="text-[15px] leading-snug text-gray-900" lang={target}>
              {captionText}
            </p>
          ) : null}
          {bilingual && captionHome && captionHome !== captionText ? (
            <p className="text-sm italic leading-snug text-gray-600" lang={home}>
              {captionHome}
            </p>
          ) : null}
          {showsPicture && picture ? <CreditLine credit={picture.credit} target={target} home={home} /> : null}
          {stage === "sticker" ? (
            <p className="text-xs leading-snug text-gray-600">{t("creditDrawing")}</p>
          ) : null}
        </figcaption>
      ) : null}
    </figure>
  );
}

export function LookCloser(props: LookCloserProps) {
  const { variant, onClose } = props;
  if (variant === "step") return <LookCloserBody {...props} />;
  return <LookCloserOverlay {...props} onClose={onClose ?? (() => {})} />;
}

/** The tap-to-open close-up: a dialog over the page. */
function LookCloserOverlay(props: LookCloserProps & { onClose: () => void }) {
  const t = useTranslations("Story");
  const label = propLabel(props.prop, props.target, props.home);
  return (
    <StoryDialog label={t("lookCloserAt", { name: label })} onClose={props.onClose}>
      {(closeButton) => <LookCloserBody {...props} closeButton={closeButton} />}
    </StoryDialog>
  );
}

/**
 * A dialog over the page, portalled to the body so no stacking context of
 * the stage can put it under the app's header or navigation. The focus goes
 * to its close button and stays inside while it is open; Esc or a tap
 * outside closes it, and the opener gives the focus back.
 */
export function StoryDialog({
  label,
  onClose,
  children,
}: {
  label: string;
  onClose: () => void;
  children: (closeButton: ReactNode) => ReactNode;
}) {
  const t = useTranslations("Story");
  const closeRef = useRef<HTMLButtonElement | null>(null);
  const dialogRef = useRef<HTMLDivElement | null>(null);
  const overlayRef = useRef<HTMLDivElement | null>(null);
  useInertBackground(overlayRef, true);

  useEffect(() => {
    closeRef.current?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        event.stopPropagation();
        onClose();
        return;
      }
      // Keep Tab inside the dialog.
      if (event.key !== "Tab" || !dialogRef.current) return;
      const focusable = dialogRef.current.querySelectorAll<HTMLElement>("button, a[href]");
      if (!focusable.length) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    // Captured, so the story's own keys (Space, the arrows) never see them.
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [onClose]);

  const closeButton = (
    <button
      ref={closeRef}
      type="button"
      onClick={onClose}
      aria-label={t("backToStory")}
      title={t("backToStory")}
      className="-mr-2 flex h-11 w-11 shrink-0 items-center justify-center rounded-full text-white hover:bg-white/15 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white"
    >
      <X className="h-5 w-5" aria-hidden="true" />
    </button>
  );
  const overlay = (
    <div
      ref={overlayRef}
      className="fixed inset-0 z-[70] flex items-end justify-center bg-black/55 p-3 sm:items-center"
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
      data-testid="story-dialog"
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-label={label}
        className="max-h-[90dvh] w-full max-w-md overflow-y-auto rounded-2xl border-[3px] border-[#1d2b4f] bg-white px-3 pb-3 shadow-[0_6px_0_rgba(29,43,79,0.25)]"
      >
        {children(closeButton)}
      </div>
    </div>
  );
  return typeof document === "undefined" ? overlay : createPortal(overlay, document.body);
}
