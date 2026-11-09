/**
 * The lesson's media region has three tabs again — Lire / Écouter / Vidéo.
 * Story mode left the lesson: a module has one story covering all its units,
 * opened from the module page, so the lesson route carries no story code.
 */

import { fireEvent, render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { describe, expect, it, vi } from "vitest";

import enMessages from "@/messages/en.json";
import frMessages from "@/messages/fr.json";

import { LessonMediaTabs } from "./lesson-media-tabs";

vi.mock("@/components/learning/lesson-audio", () => ({
  LessonAudio: () => <p>audio pane</p>,
}));
vi.mock("@/components/learning/lesson-video", () => ({
  LessonVideo: () => <p>video pane</p>,
}));

function renderTabs(locale: "fr" | "en", onActiveTabChange = vi.fn()) {
  render(
    <NextIntlClientProvider locale={locale} messages={locale === "fr" ? frMessages : enMessages}>
      <LessonMediaTabs
        lessonId="lesson-1"
        language={locale}
        readPane={<p>Corps de la leçon</p>}
        onActiveTabChange={onActiveTabChange}
      />
    </NextIntlClientProvider>,
  );
  return onActiveTabChange;
}

describe("LessonMediaTabs", () => {
  it("offers read, listen and watch, and no story tab", () => {
    renderTabs("fr");
    const tabs = screen.getAllByRole("tab").map((tab) => tab.textContent);
    expect(tabs).toEqual(["Lire", "Écouter", "Vidéo"]);
    expect(screen.queryByRole("tab", { name: /Histoire/ })).not.toBeInTheDocument();
    expect(screen.getByText("Corps de la leçon")).toBeInTheDocument();
  });

  it("has the same three tabs in English", () => {
    renderTabs("en");
    expect(screen.getAllByRole("tab").map((tab) => tab.textContent)).toEqual([
      "Read",
      "Listen",
      "Video",
    ]);
  });

  it("tells the parent which tab is open", () => {
    const onActiveTabChange = renderTabs("fr");
    fireEvent.click(screen.getByRole("tab", { name: /Écouter/ }));
    expect(onActiveTabChange).toHaveBeenLastCalledWith("listen");
    fireEvent.click(screen.getByRole("tab", { name: /Vidéo/ }));
    expect(onActiveTabChange).toHaveBeenLastCalledWith("watch");
  });
});
