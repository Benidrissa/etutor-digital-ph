/**
 * The weekly story host (#2738): the player is a lazy chunk, so the host shows
 * its skeleton while the week is fetched and again while the chunk comes, then
 * the player. The chunk is held back by a gate here to see both states.
 */

import { act, cleanup, render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { getStoryCourse } from "@/lib/story-course/api";
import type { StoryCourse } from "@/lib/story-course/types";
import frMessages from "@/messages/fr.json";

const chunk = vi.hoisted(() => ({
  release: () => {},
  gate: null as Promise<void> | null,
}));

vi.mock("@/components/story/story-player", async () => {
  // Resolves only when the test releases the "network".
  await chunk.gate;
  return { StoryPlayer: () => <div data-testid="player" /> };
});

vi.mock("@/lib/story-course/api", () => ({ getStoryCourse: vi.fn() }));

import { StoryWeek } from "./story-week";

const COURSE = { id: "week-1", chapters: [] } as unknown as StoryCourse;

function renderWeek() {
  return render(
    <NextIntlClientProvider locale="fr" messages={frMessages}>
      <StoryWeek slug="week-1" />
    </NextIntlClientProvider>,
  );
}

beforeEach(() => {
  window.localStorage.clear();
  vi.mocked(getStoryCourse).mockReset();
});

afterEach(() => {
  cleanup();
});

describe("StoryWeek", () => {
  it("shows the skeleton while the week loads, and again while the player chunk comes", async () => {
    vi.resetModules();
    chunk.gate = new Promise<void>((resolve) => {
      chunk.release = resolve;
    });
    let resolveWeek: (course: StoryCourse) => void = () => {};
    vi.mocked(getStoryCourse).mockReturnValue(
      new Promise<StoryCourse>((resolve) => {
        resolveWeek = resolve;
      }),
    );
    renderWeek();

    // The week is not here yet: the skeleton, and no player.
    expect(document.querySelector("main[aria-busy='true']")).not.toBeNull();
    expect(screen.queryByTestId("player")).not.toBeInTheDocument();

    // The week is here, the chunk is not: still the same skeleton.
    await act(async () => resolveWeek(COURSE));
    expect(document.querySelector("main[aria-busy='true']")).not.toBeNull();
    expect(screen.queryByTestId("player")).not.toBeInTheDocument();

    // The chunk arrives: the player replaces the skeleton.
    await act(async () => chunk.release());
    expect(await screen.findByTestId("player")).toBeInTheDocument();
    expect(document.querySelector("main[aria-busy='true']")).toBeNull();
  });

  it("says so when the week cannot be loaded", async () => {
    chunk.gate = Promise.resolve();
    vi.mocked(getStoryCourse).mockRejectedValue(new Error("offline"));
    renderWeek();
    expect(await screen.findByText(/./, { selector: "p.text-red-800" })).toBeInTheDocument();
  });
});
