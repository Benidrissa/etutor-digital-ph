/**
 * The floating tutor button stays off the story player's « Suite » (#2688):
 * on a story page it is hidden below a wide desktop, where the story column
 * leaves the corner free.
 */

import { render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

const pathname = vi.hoisted(() => ({ value: "/fr/dashboard" }));

vi.mock("next/navigation", () => ({ usePathname: () => pathname.value }));

vi.mock("@/components/chat", () => ({
  ChatProvider: ({ children }: { children: ReactNode }) => <>{children}</>,
  useChatContext: () => ({ isOpen: false, closeChat: vi.fn(), toggleChat: vi.fn() }),
  ChatPanel: () => null,
  FloatingChatButton: ({ className }: { className?: string }) => (
    <button type="button" aria-label="tutor" className={className} />
  ),
}));

import { ChatLayout } from "./chat-layout";

afterEach(() => {
  pathname.value = "/fr/dashboard";
});

function fab() {
  return screen.queryByRole("button", { name: "tutor" });
}

describe("ChatLayout — the floating tutor button", () => {
  it.each(["/fr/modules/6f1c2d3e-4b5a-6978-8a9b-0c1d2e3f4a5b/story", "/en/story/week-1-fr", "/fr/modules/m1/story/"])(
    "is hidden below a wide desktop on %s",
    (path) => {
      pathname.value = path;
      render(<ChatLayout>page</ChatLayout>);
      expect(fab()?.className).toContain("max-xl:hidden");
    },
  );

  it.each(["/fr/dashboard", "/fr/modules/m1", "/fr/modules/m1/units/1.1", "/fr/stories"])(
    "is shown at every width on %s",
    (path) => {
      pathname.value = path;
      render(<ChatLayout>page</ChatLayout>);
      expect(fab()).not.toBeNull();
      expect(fab()?.className ?? "").not.toContain("max-xl:hidden");
    },
  );

  it("still stays away from the tutor page itself", () => {
    pathname.value = "/fr/tutor";
    render(<ChatLayout>page</ChatLayout>);
    expect(fab()).toBeNull();
  });
});
