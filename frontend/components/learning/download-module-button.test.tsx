/**
 * The download progress line names what is being saved. The story is one per
 * module, saved once after the units, so its line carries no unit number
 * (the downloader sends no currentUnit for it).
 */

import { render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { describe, expect, it, vi } from "vitest";

import type { DownloadProgress } from "@/lib/offline/download-manager";
import enMessages from "@/messages/en.json";
import frMessages from "@/messages/fr.json";

import { DownloadModuleButton } from "./download-module-button";

const state = vi.hoisted(() => ({
  progress: null as DownloadProgress | null,
}));

vi.mock("@/lib/hooks/use-download-manager", () => ({
  useDownloadManager: () => ({
    status: "downloading",
    progress: state.progress,
    isDownloading: true,
    isAvailableOffline: false,
    canDownload: true,
    estimatedSize: 100_000,
    downloadedUnits: 4,
    totalUnits: 4,
    error: null,
    download: vi.fn(),
    cancel: vi.fn(),
    remove: vi.fn(),
  }),
}));

function renderButton(locale: "fr" | "en") {
  render(
    <NextIntlClientProvider locale={locale} messages={locale === "fr" ? frMessages : enMessages}>
      <DownloadModuleButton moduleId="mod-1" locale={locale} unitCount={4} />
    </NextIntlClientProvider>,
  );
}

const storyTick: DownloadProgress = {
  phase: "downloading_content",
  totalUnits: 4,
  downloadedUnits: 4,
  currentContentType: "story",
};

describe("DownloadModuleButton — progress label", () => {
  it("names the module story, with no unit, while it is being saved", () => {
    state.progress = storyTick;
    renderButton("fr");
    expect(screen.getByText("Téléchargement de l'histoire du module")).toBeInTheDocument();
  });

  it("has the module story label in English too", () => {
    state.progress = storyTick;
    renderButton("en");
    expect(screen.getByText("Downloading the module story")).toBeInTheDocument();
  });

  it("still names the unit for its lesson, quiz and case study", () => {
    state.progress = {
      phase: "downloading_content",
      totalUnits: 4,
      downloadedUnits: 1,
      currentUnit: "1.2",
      currentContentType: "lesson",
    };
    renderButton("fr");
    expect(screen.getByText("Téléchargement de la leçon 1.2")).toBeInTheDocument();
  });

  it("shows no line before any content is being saved", () => {
    state.progress = { phase: "fetching_structure", totalUnits: 0, downloadedUnits: 0 };
    renderButton("fr");
    expect(screen.queryByText(/Téléchargement de/)).not.toBeInTheDocument();
  });
});
