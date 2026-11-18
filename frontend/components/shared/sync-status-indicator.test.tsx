/**
 * The sync banner must tell the learner when queued quiz answers were dropped
 * because the quiz changed (409 quiz_changed) — also when another queued
 * action failed in the same sync. The dropped answers are gone from the queue
 * by then, so a retry would never report them.
 */

import { render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { describe, expect, it, vi } from "vitest";

import type { SyncStatus } from "@/lib/offline/sync-manager";
import messages from "@/messages/en.json";

const hook = vi.hoisted(() => ({ status: { state: "idle" } as SyncStatus }));

vi.mock("@/lib/hooks/use-sync-status", () => ({
  useSyncStatus: () => ({
    status: hook.status,
    pendingCount: 0,
    isSyncing: hook.status.state === "syncing",
    syncNow: vi.fn(),
  }),
}));

import { SyncStatusIndicator } from "./sync-status-indicator";

function renderWith(status: SyncStatus) {
  hook.status = status;
  render(
    <NextIntlClientProvider locale="en" messages={messages}>
      <SyncStatusIndicator />
    </NextIntlClientProvider>,
  );
}

describe("SyncStatusIndicator", () => {
  it("reports dropped quiz answers alongside a failed sync", () => {
    renderWith({ state: "error", message: "1 actions failed", synced: 0, failed: 1, quizChanged: 1 });

    expect(screen.getByText("Sync failed")).toBeInTheDocument();
    expect(screen.getByText(/A quiz you answered offline was updated/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry sync" })).toBeInTheDocument();
  });

  it("says nothing about quizzes when none were dropped", () => {
    renderWith({ state: "error", message: "1 actions failed", synced: 0, failed: 1, quizChanged: 0 });

    expect(screen.getByText("Sync failed")).toBeInTheDocument();
    expect(screen.queryByText(/answered offline was updated/)).toBeNull();
  });

  it("reports them when everything else synced", () => {
    renderWith({ state: "complete", synced: 2, quizChanged: 2 });

    expect(screen.getByText(/2 quizzes you answered offline were updated/)).toBeInTheDocument();
  });
});
