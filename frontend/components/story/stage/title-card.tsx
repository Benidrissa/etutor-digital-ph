/**
 * The cards that open a story: the title card painted on the stage at the
 * start of every chapter, and the start card that asks the learner for their
 * best friend's name and which hero they are (#2672), once per course.
 */

import { useTranslations } from "next-intl";
import { useId, useState, type FormEvent } from "react";

import { FIGURE_HEIGHT, type StageActor } from "./cast";
import { PlaceholderFigure } from "./placeholder-figure";
import styles from "./stage.module.css";

interface TitleCardProps {
  eyebrow?: string;
  title: string;
  titleLang: string;
  subtitle?: string;
  subtitleLang: string;
  footer?: string;
}

/** Painted on the stage; the chapter heading itself is in the player header. */
export function TitleCard({ eyebrow, title, titleLang, subtitle, subtitleLang, footer }: TitleCardProps) {
  return (
    <div
      className={`${styles.popIn} absolute left-1/2 top-[5%] z-[1] w-[78%] -translate-x-1/2 rounded-[1.4rem] px-[4%] py-[3%] text-center shadow-[0_6px_0_rgba(0,0,0,0.18)]`}
      style={{ background: "rgb(38 50 79 / 0.92)" }}
      aria-hidden="true"
      data-title-card=""
    >
      {eyebrow ? (
        <p className={`${styles.subtitleSize} truncate font-bold uppercase tracking-wider text-[#8fe3d0]`}>{eyebrow}</p>
      ) : null}
      <p className={`${styles.titleSize} ${styles.titleText} mt-1 font-black`} lang={titleLang}>
        {title}
      </p>
      {subtitle ? (
        <p className={`${styles.subtitleSize} mt-1 font-semibold italic text-white`} lang={subtitleLang}>
          {subtitle}
        </p>
      ) : null}
      {footer ? (
        <p className={`${styles.subtitleSize} ${styles.wideOnly} mt-1 font-semibold text-[#a9d6e5]`}>{footer}</p>
      ) : null}
    </div>
  );
}

/** A small "you are here" ribbon when a new place starts. */
export function PlaceRibbon({ label, lang }: { label: string; lang: string }) {
  return (
    <p
      className={`${styles.fadeIn} absolute left-[3%] top-[4%] z-[1] rounded-full border-2 border-[#ffd23f] px-3 py-1 text-xs font-extrabold text-[#ffd23f] shadow`}
      style={{ background: "rgb(29 43 79 / 0.88)" }}
      lang={lang}
      aria-hidden="true"
    >
      <svg viewBox="0 0 12 16" width="10" height="13" className="mr-1 inline-block align-[-1px]" aria-hidden="true">
        <path d="M6,15 C6,15 1,9 1,5.5 A5,5 0 0 1 11,5.5 C11,9 6,15 6,15 Z" fill="#ffd23f" />
        <circle cx="6" cy="5.5" r="2" fill="#1d2b4f" />
      </svg>
      {label}
    </p>
  );
}

interface StartCardProps {
  askFriend: boolean;
  defaultFriend: string;
  initialFriend?: string;
  /** The hero's looks to choose from, each drawn as it will appear. */
  variants: Array<{ id: string; actor: StageActor; artUrl?: string }>;
  initialVariant?: string;
  /** The look being tried on, so the hero on stage can wear it already. */
  onPreview?: (variant: string) => void;
  onStart: (choices: { friend?: string; variant?: string }) => void;
}

/** The learner's choices before the story starts, in the dialogue area. */
export function StartCard({
  askFriend,
  defaultFriend,
  initialFriend,
  variants,
  initialVariant,
  onPreview,
  onStart,
}: StartCardProps) {
  const t = useTranslations("Story");
  const inputId = useId();
  const legendId = useId();
  const [friend, setFriend] = useState(initialFriend ?? "");
  const [variant, setVariant] = useState(initialVariant ?? variants[0]?.id);

  const submit = (event?: FormEvent) => {
    event?.preventDefault();
    onStart({
      friend: askFriend ? friend.trim().slice(0, 40) || undefined : undefined,
      variant: variants.length ? variant : undefined,
    });
  };

  const variantLabel = (id: string) =>
    ["girl", "boy", "woman", "man"].includes(id) ? t(`variant.${id}` as "variant.girl") : id;

  return (
    <form
      onSubmit={submit}
      className={`${styles.panel} ${styles.start} ${styles.rise} rounded-2xl border-[3px] border-[#1d2b4f] bg-white p-4 shadow-[0_6px_0_rgba(29,43,79,0.25)]`}
      data-step-panel="start"
    >
      {variants.length ? (
        <fieldset aria-labelledby={legendId}>
          <p id={legendId} className="font-bold text-gray-900">
            {t("pickHero")}
          </p>
          <div className="mt-2 flex gap-3">
            {variants.map(({ id, actor, artUrl }) => {
              const chosen = id === variant;
              return (
                <button
                  key={id}
                  type="button"
                  onClick={() => {
                    setVariant(id);
                    onPreview?.(id);
                  }}
                  aria-pressed={chosen}
                  className={`flex min-h-11 flex-1 items-center gap-2 rounded-xl border-[3px] px-2 py-1 text-left font-bold focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#1d6fb8] ${
                    chosen ? "border-[#1d2b4f] bg-[#fff4c2]" : "border-gray-300 bg-white hover:border-[#1d6fb8]"
                  }`}
                >
                  <span
                    className="flex shrink-0 items-end justify-center"
                    style={{ height: `${Math.round(FIGURE_HEIGHT[actor.figure] * 1.25)}px` }}
                    aria-hidden="true"
                  >
                    {artUrl ? (
                      // eslint-disable-next-line @next/next/no-img-element -- generated art from the story API
                      <img src={artUrl} alt="" className="h-full w-auto" />
                    ) : (
                      <PlaceholderFigure actor={actor} pose={chosen ? "happy" : "idle"} />
                    )}
                  </span>
                  <span className="text-gray-900">{variantLabel(id)}</span>
                </button>
              );
            })}
          </div>
        </fieldset>
      ) : null}

      {askFriend ? (
        <div className={variants.length ? "mt-3" : ""}>
          <label htmlFor={inputId} className="block font-bold text-gray-900">
            {t("friendPrompt")}
          </label>
          <input
            id={inputId}
            value={friend}
            onChange={(event) => setFriend(event.target.value)}
            maxLength={40}
            autoComplete="off"
            placeholder={defaultFriend}
            className="mt-2 min-h-12 w-full rounded-full border-[3px] border-[#ffd23f] bg-[#fffdf3] px-4 text-lg text-gray-900 focus-visible:border-[#1d6fb8] focus-visible:outline-none"
          />
          <p className="mt-1 text-xs text-gray-600">{t("friendHint", { name: defaultFriend })}</p>
        </div>
      ) : null}

      <button
        type="submit"
        className="mt-3 flex min-h-12 w-full items-center justify-center gap-2 rounded-full border-[3px] border-[#ffd23f] bg-[#1d2b4f] px-6 text-lg font-extrabold text-white shadow-[0_4px_0_rgba(0,0,0,0.25)] hover:bg-[#263a69] focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-[#ffd23f]/60"
      >
        {t("play")}
        <PlayIcon />
      </button>
    </form>
  );
}

export function PlayIcon() {
  return (
    <svg viewBox="0 0 20 20" width="22" height="22" aria-hidden="true" focusable="false">
      <path d="M5,3 L17,10 L5,17 Z" fill="#ffd23f" stroke="#ffd23f" strokeWidth="2" strokeLinejoin="round" />
    </svg>
  );
}
