/**
 * Concept visuals as the learner sees them.
 *
 * Lesson stories show figures from the course's own documents as a `show` step
 * with visual "image" (contract X4). That used to fall through to the
 * "not drawn yet" box, which printed the step's raw params — JSON with an
 * image id — on the learner's screen.
 */

import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import { afterEach, describe, expect, it, vi } from "vitest";

import enMessages from "@/messages/en.json";
import frMessages from "@/messages/fr.json";
import type { StoryCourse } from "@/lib/story-course/types";

import { ConceptVisual } from "./concept-visual";
import { StoryPlayer } from "./story-player";

// The image step renders the whole cartoon stage: headroom on a busy runner.
vi.setConfig({ testTimeout: 20_000 });

const figureParams = {
  source_image_id: "0f1e2d3c-img",
  figure_number: "Figure 2.1",
  alt: { en: "Hands under running water", fr: "Des mains sous l'eau courante" },
};

function renderVisual(
  props: React.ComponentProps<typeof ConceptVisual>,
  locale: "fr" | "en" = "fr",
) {
  return render(
    <NextIntlClientProvider locale={locale} messages={locale === "fr" ? frMessages : enMessages}>
      <ConceptVisual {...props} />
    </NextIntlClientProvider>,
  );
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("ConceptVisual — source figures (X4)", () => {
  it("draws an image step with the lesson's SourceImage, in the learner's language", () => {
    renderVisual({
      visual: "image",
      params: figureParams,
      caption: "Le lavage des mains",
      language: "fr",
    });

    const img = screen.getByRole("img", { name: "Des mains sous l'eau courante" });
    expect(img.getAttribute("src")).toContain("/api/v1/source-images/0f1e2d3c-img/data?lang=fr");
    // SourceImage's own figure label: localized "Figure", the number, the caption.
    expect(screen.getByText("Figure 2.1 — Le lavage des mains")).toBeInTheDocument();
    // Opens full screen like any lesson figure.
    expect(screen.getByRole("button", { name: /plein écran/i })).toBeInTheDocument();
    expect(screen.queryByText(/source_image_id/)).not.toBeInTheDocument();
  });

  it("uses the English alt text for an English learner", () => {
    renderVisual({ visual: "image", params: figureParams, language: "en" }, "en");
    const img = screen.getByRole("img", { name: "Hands under running water" });
    expect(img.getAttribute("src")).toContain("data?lang=en");
  });

  it("renders nothing when the image id is missing", () => {
    const { container } = renderVisual({
      visual: "image",
      params: { figure_number: "2.1", alt: { en: "x", fr: "x" } },
      caption: "Une légende",
      language: "fr",
    });
    expect(container).toBeEmptyDOMElement();
  });

  it("credits the figure (#2681)", () => {
    renderVisual({
      visual: "image",
      params: { ...figureParams, attribution: "OpenStax, CC BY 4.0" },
      language: "fr",
    });
    expect(screen.getByText("OpenStax, CC BY 4.0")).toBeInTheDocument();
  });

  it("says the picture is missing instead of leaving an empty box (#2681)", () => {
    renderVisual({ visual: "image", params: figureParams, caption: "Le lavage des mains", language: "fr" });
    fireEvent.error(screen.getByRole("img", { name: "Des mains sous l'eau courante" }));
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
    expect(screen.getByText("Cette illustration n'est pas encore disponible.")).toBeInTheDocument();
    expect(screen.getByText("Le lavage des mains")).toBeInTheDocument();
  });

  it("opens the full-screen view over the whole page, not inside the stage (#2682)", async () => {
    const user = userEvent.setup();
    const { container } = renderVisual({ visual: "image", params: figureParams, language: "fr" });
    await user.click(screen.getByRole("button", { name: /plein écran/i }));
    const viewer = screen.getByRole("dialog");
    // Portalled to the body: no stacking context of the stage can hide it.
    expect(container.contains(viewer)).toBe(false);
    expect(viewer.parentElement).toBe(document.body);
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});

describe("ConceptVisual — a prop's close-up outside the stage (#2681)", () => {
  it("draws nothing: only the stage player shows props", () => {
    const { container } = renderVisual({ visual: "prop", params: { prop: "snail" }, language: "fr" });
    expect(container).toBeEmptyDOMElement();
  });
});

describe("ConceptVisual — a visual the player does not draw yet", () => {
  it("shows a neutral placeholder, never the raw params", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    renderVisual({
      visual: "bar_chart",
      params: { series: [3, 5, 8], secret_id: "abc" },
      caption: "Les cas par mois",
    });

    expect(screen.getByText("Cette illustration n'est pas encore disponible.")).toBeInTheDocument();
    expect(screen.getByText("Les cas par mois")).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/bar_chart|series|secret_id|\[3,5,8\]/);
    // The details are kept for whoever adds the widget.
    expect(warn).toHaveBeenCalledWith(
      expect.stringContaining("bar_chart"),
      expect.objectContaining({ secret_id: "abc" }),
    );
  });

  it("still draws the catalogue widgets", () => {
    renderVisual({ visual: "division_ladder", params: { n: 12 } });
    expect(screen.getByRole("img", { name: "division_ladder diagram" })).toBeInTheDocument();
    expect(screen.getByText(/12 = /)).toBeInTheDocument();
  });
});

describe("StoryPlayer — image step", () => {
  it("shows a lesson figure in the story's target language", async () => {
    const user = userEvent.setup();
    const story: StoryCourse = {
      format: "story-course/1",
      id: "lesson-0123456789abcdef-fr",
      week: 1,
      title: { en: "Clean hands", fr: "Des mains propres" },
      languages: { target: "fr", home: "en" },
      learner: { first_name: "Awa" },
      objectives: [],
      cast: [],
      chapters: [
        {
          id: "c1",
          title: { en: "At the clinic", fr: "Au centre de santé" },
          scenes: [
            {
              id: "s1",
              place: "classroom",
              steps: [
                { type: "narrate", en: "Look.", fr: "Regarde." },
                {
                  type: "show",
                  visual: "image",
                  params: figureParams,
                  caption: { en: "Hand washing", fr: "Le lavage des mains" },
                },
              ],
            },
          ],
        },
      ],
      questions: [],
      checks: { max_points: 0 },
    } as unknown as StoryCourse;

    render(
      <NextIntlClientProvider locale="fr" messages={frMessages}>
        <StoryPlayer course={story} variant="embedded" />
      </NextIntlClientProvider>,
    );
    await user.click(screen.getByRole("button", { name: "Suite" }));

    const img = screen.getByRole("img", { name: "Des mains sous l'eau courante" });
    expect(img.getAttribute("src")).toContain("data?lang=fr");
    expect(screen.getByText("Figure 2.1 — Le lavage des mains")).toBeInTheDocument();
  });
});
