/**
 * The module page's story card: its states come from the status route (which
 * never generates or sends the story) and from this browser's progress, and
 * it shows only on an unlocked module.
 */

import { act, render, screen, waitFor } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, getModuleDetailWithProgress } from "@/lib/api";
import { getModuleStoryStatus } from "@/lib/story-course/api";
import { moduleStoryId, storyProgressKey } from "@/lib/story-course/progress";
import type { ModuleStoryStatus } from "@/lib/story-course/types";
import enMessages from "@/messages/en.json";
import frMessages from "@/messages/fr.json";

import { ModuleLockGate } from "./module-lock-gate";
import { ModuleStoryCard } from "./module-story-card";

vi.mock("@/lib/story-course/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/story-course/api")>();
  return { ...actual, getModuleStoryStatus: vi.fn() };
});

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    getModuleDetailWithProgress: vi.fn(),
    getModuleUnits: vi.fn(),
    canAttemptSummativeAssessment: vi.fn(() => Promise.resolve(null)),
  };
});

vi.mock("@/i18n/routing", () => ({
  Link: ({ href, children, ...rest }: { href: unknown; children: ReactNode }) => (
    <a href={typeof href === "string" ? href : "#"} {...rest}>
      {children}
    </a>
  ),
}));

// The module page's other panels are not under test here.
vi.mock("@/lib/analytics", () => ({ track: vi.fn() }));
vi.mock("@/components/learning/module-progress-overlay", () => ({
  ModuleProgressOverlay: () => null,
}));
vi.mock("@/components/learning/download-module-button", () => ({
  DownloadModuleButton: () => null,
}));

const statusMock = vi.mocked(getModuleStoryStatus);
const detailMock = vi.mocked(getModuleDetailWithProgress);

const MODULE_ID = "6f1c2d3e-4b5a-6978-8a9b-0c1d2e3f4a5b";
const STORY_ID = moduleStoryId(MODULE_ID, "fr");
const USER_ID = "u1";

function status(overrides: Partial<ModuleStoryStatus> = {}): ModuleStoryStatus {
  return {
    state: "ready",
    task_id: null,
    chapters: 4,
    revision: "0123456789abcdef",
    access: "ok",
    ...overrides,
  };
}

function saveProgress(completedUnits: string[], userId = USER_ID) {
  window.localStorage.setItem(
    storyProgressKey(STORY_ID, userId),
    JSON.stringify({ v: 1, completedUnits, points: {} }),
  );
}

function renderCard(locale: "fr" | "en" = "fr") {
  return render(
    <NextIntlClientProvider locale={locale} messages={locale === "fr" ? frMessages : enMessages}>
      <ModuleStoryCard moduleId={MODULE_ID} language={locale} />
    </NextIntlClientProvider>,
  );
}

async function cardLink() {
  return screen.findByRole("link", { name: /Histoire du module/ });
}

beforeEach(() => {
  statusMock.mockReset();
  detailMock.mockReset();
  window.localStorage.setItem(
    "user",
    JSON.stringify({ id: USER_ID, email: null, name: "Awa", preferred_language: "fr", current_level: 1 }),
  );
});

afterEach(() => {
  window.localStorage.clear();
});

describe("ModuleStoryCard", () => {
  it("asks the status route for the interface language", async () => {
    statusMock.mockResolvedValue(status());
    renderCard();
    await cardLink();
    expect(statusMock).toHaveBeenCalledWith(MODULE_ID, "fr");
  });

  it("offers to start a ready story nobody has opened here", async () => {
    statusMock.mockResolvedValue(status());
    renderCard();
    const link = await cardLink();
    expect(link).toHaveAttribute("href", `/modules/${MODULE_ID}/story`);
    expect(link).toHaveTextContent(
      "Tout le module raconté comme une histoire, chapitre par chapitre",
    );
    // 44px touch target.
    expect(link.className).toMatch(/min-h-11/);
  });

  it("offers to start a story not written yet (opening it writes it)", async () => {
    statusMock.mockResolvedValue(status({ state: "not_ready", chapters: null, revision: null }));
    renderCard();
    expect(await cardLink()).toHaveTextContent("Tout le module raconté");
  });

  it("resumes at the next chapter from this browser's progress", async () => {
    saveProgress(["unit-1", "unit-2"]);
    statusMock.mockResolvedValue(status());
    renderCard();
    expect(await cardLink()).toHaveTextContent("Continuer — chapitre 3 sur 4");
  });

  it("says the story is finished once every chapter is done", async () => {
    saveProgress(["a", "b", "c", "d"]);
    statusMock.mockResolvedValue(status());
    renderCard();
    expect(await cardLink()).toHaveTextContent("Histoire terminée — la rejouer");
  });

  it("never shows another learner's progress (a shared phone)", async () => {
    saveProgress(["a", "b", "c", "d"], "another-learner");
    statusMock.mockResolvedValue(status());
    renderCard();
    const link = await cardLink();
    expect(link).toHaveTextContent("Tout le module raconté");
    expect(link).not.toHaveTextContent("Histoire terminée");
  });

  it("says the story is being written", async () => {
    statusMock.mockResolvedValue(status({ state: "generating", task_id: "task-1" }));
    renderCard();
    expect(await cardLink()).toHaveTextContent("En cours d'écriture");
  });

  it("says the story is for subscribers when the module has paid units", async () => {
    statusMock.mockResolvedValue(status({ access: "subscription_required" }));
    renderCard();
    expect(await cardLink()).toHaveTextContent("Réservé aux abonnés");
  });

  it("says the story is not available yet", async () => {
    statusMock.mockResolvedValue(status({ state: "unavailable" }));
    renderCard();
    expect(await cardLink()).toHaveTextContent("Pas encore disponible");
  });

  it("shows nothing when story mode is switched off", async () => {
    statusMock.mockResolvedValue(status({ state: "disabled", chapters: null }));
    const { container } = renderCard();
    await waitFor(() => expect(statusMock).toHaveBeenCalled());
    // Let the answer settle: the card must stay away, not just be loading.
    await act(async () => {});
    expect(container).toBeEmptyDOMElement();
  });

  it("shows nothing for an unknown module", async () => {
    statusMock.mockRejectedValue(
      new ApiError("Module not found", 404, undefined, { error: "module_not_found" }),
    );
    const { container } = renderCard();
    await waitFor(() => expect(statusMock).toHaveBeenCalled());
    // Let the answer settle: the card must stay away, not just be loading.
    await act(async () => {});
    expect(container).toBeEmptyDOMElement();
  });

  it("still links to the story when the status cannot be fetched (offline)", async () => {
    saveProgress(["unit-1"]);
    statusMock.mockRejectedValue(new TypeError("Failed to fetch"));
    renderCard();
    expect(await cardLink()).toHaveAttribute("href", `/modules/${MODULE_ID}/story`);
  });

  it("speaks English on the English page", async () => {
    statusMock.mockResolvedValue(status({ state: "generating" }));
    render(
      <NextIntlClientProvider locale="en" messages={enMessages}>
        <ModuleStoryCard moduleId={MODULE_ID} language="en" />
      </NextIntlClientProvider>,
    );
    const link = await screen.findByRole("link", { name: /Module story/ });
    expect(link).toHaveTextContent("Being written");
    expect(statusMock).toHaveBeenCalledWith(MODULE_ID, "en");
  });
});

describe("ModuleLockGate — the story card's place", () => {
  function detail(state: "locked" | "in_progress") {
    return {
      id: MODULE_ID,
      module_number: 1,
      level: 1,
      title_fr: "Hygiène",
      title_en: "Hygiene",
      estimated_hours: 2,
      prereq_modules: [],
      status: state,
      completion_pct: 0,
      quiz_score_avg: null,
      time_spent_minutes: 0,
      last_accessed: null,
      units: [],
    };
  }

  function renderGate() {
    return render(
      <NextIntlClientProvider locale="fr" messages={frMessages}>
        <ModuleLockGate moduleId={MODULE_ID} language="fr" />
      </NextIntlClientProvider>,
    );
  }

  it("shows the card between the header and the units on an unlocked module", async () => {
    detailMock.mockResolvedValue(detail("in_progress"));
    statusMock.mockResolvedValue(status());
    renderGate();

    const link = await cardLink();
    const heading = screen.getByRole("heading", { level: 1, name: "Hygiène" });
    expect(heading.compareDocumentPosition(link) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("does not ask about the story on a locked module", async () => {
    detailMock.mockResolvedValue(detail("locked"));
    statusMock.mockResolvedValue(status());
    renderGate();

    expect(await screen.findByText("Module verrouillé")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Histoire du module/ })).not.toBeInTheDocument();
    expect(statusMock).not.toHaveBeenCalled();
  });
});
