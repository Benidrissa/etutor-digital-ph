/**
 * The Story tab's code is split out of the lesson page: the panel and the whole
 * story player (~10 KB gzipped) are fetched only when a learner first opens
 * the tab, with a skeleton meanwhile. Every other lesson view pays nothing.
 */

import { act, fireEvent, render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { describe, expect, it, vi } from "vitest";

import frMessages from "@/messages/fr.json";

import { LessonMediaTabs } from "./lesson-media-tabs";

// Records when the panel's module is evaluated, and holds it back until the
// test lets it through, so the loading state can be seen.
const panel = vi.hoisted(() => {
  let release: () => void = () => {};
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  return { loaded: false, gate, release: () => release() };
});

vi.mock("./lesson-story", async () => {
  panel.loaded = true;
  await panel.gate;
  return {
    LessonStory: ({ active, unitId }: { active: boolean; unitId: string }) => (
      <p>{`story panel ${unitId} ${active ? "open" : "hidden"}`}</p>
    ),
  };
});

vi.mock("@/components/learning/lesson-audio", () => ({ LessonAudio: () => null }));
vi.mock("@/components/learning/lesson-video", () => ({ LessonVideo: () => null }));

describe("LessonMediaTabs — lazy Story tab", () => {
  it("loads the story panel's code only when the Story tab is first opened", async () => {
    render(
      <NextIntlClientProvider locale="fr" messages={frMessages}>
        <LessonMediaTabs
          lessonId="lesson-1"
          moduleId="mod-1"
          unitId="1.2"
          language="fr"
          readPane={<p>Corps de la leçon</p>}
        />
      </NextIntlClientProvider>,
    );

    await act(async () => {});
    expect(screen.getByText("Corps de la leçon")).toBeInTheDocument();
    expect(panel.loaded).toBe(false);

    fireEvent.click(screen.getByRole("tab", { name: /Histoire/ }));
    await act(async () => {});
    expect(panel.loaded).toBe(true);
    // The skeleton holds the place while the chunk downloads.
    expect(screen.getByText("Chargement de l'histoire…")).toBeInTheDocument();

    await act(async () => {
      panel.release();
    });
    expect(await screen.findByText("story panel 1.2 open")).toBeInTheDocument();

    // Kept mounted, and told it is hidden, once another tab is open.
    fireEvent.click(screen.getByRole("tab", { name: /Lire/ }));
    expect(await screen.findByText("story panel 1.2 hidden")).toBeInTheDocument();
  });
});
