/**
 * The download progress line names what is being saved, the lesson's story
 * included (it used to go blank while a story was fetched).
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
    downloadedUnits: 1,
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

describe("DownloadModuleButton — progress label", () => {
  it("names the story while a lesson's story is being saved", () => {
    state.progress = {
      phase: "downloading_content",
      totalUnits: 4,
      downloadedUnits: 1,
      currentUnit: "1.2",
      currentContentType: "story",
    };
    renderButton("fr");
    expect(screen.getByText("Téléchargement de l'histoire 1.2")).toBeInTheDocument();
  });

  it("has the label in English too", () => {
    state.progress = {
      phase: "downloading_content",
      totalUnits: 4,
      downloadedUnits: 1,
      currentUnit: "1.3",
      currentContentType: "story",
    };
    renderButton("en");
    expect(screen.getByText("Downloading story 1.3")).toBeInTheDocument();
  });
});
