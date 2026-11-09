/**
 * The module story route (/{locale}/modules/{moduleId}/story): it sits behind
 * the enrollment guard, links back to the module, and hands the panel the
 * module and the interface language.
 */

import { render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import ModuleStoryPage, {
  generateMetadata,
} from "@/app/[locale]/(app)/modules/[moduleId]/story/page";

const MODULE_ID = "6f1c2d3e-4b5a-6978-8a9b-0c1d2e3f4a5b";

vi.mock("next-intl/server", () => ({
  getTranslations: vi.fn(async ({ locale }: { locale: string }) => (key: string) =>
    `${locale}:${key}`,
  ),
}));

vi.mock("@/i18n/routing", () => ({
  Link: ({ href, children, ...rest }: { href: string; children: ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

vi.mock("@/components/shared/enrollment-guard", () => ({
  EnrollmentGuard: ({ moduleId, children }: { moduleId: string; children: ReactNode }) => (
    <div data-testid="enrollment-guard" data-module={moduleId}>
      {children}
    </div>
  ),
}));

vi.mock("@/components/learning/module-story", () => ({
  ModuleStory: ({ moduleId, language }: { moduleId: string; language: string }) => (
    <div data-testid="module-story" data-module={moduleId} data-language={language} />
  ),
}));

async function renderPage(locale: string) {
  const element = await ModuleStoryPage({
    params: Promise.resolve({ locale, moduleId: MODULE_ID }),
  });
  return render(element);
}

describe("module story route", () => {
  it("renders the panel inside the enrollment guard, with a back link", async () => {
    await renderPage("fr");

    const guard = screen.getByTestId("enrollment-guard");
    expect(guard).toHaveAttribute("data-module", MODULE_ID);
    const panel = screen.getByTestId("module-story");
    expect(guard).toContainElement(panel);
    expect(panel).toHaveAttribute("data-module", MODULE_ID);
    expect(panel).toHaveAttribute("data-language", "fr");

    const back = screen.getByRole("link", { name: "fr:backToModule" });
    expect(back).toHaveAttribute("href", `/modules/${MODULE_ID}`);
    // 44px touch target.
    expect(back.className).toMatch(/min-h-11/);
  });

  it("passes English to the panel on the English route", async () => {
    await renderPage("en");
    expect(screen.getByTestId("module-story")).toHaveAttribute("data-language", "en");
  });

  it("titles the page", async () => {
    await expect(
      generateMetadata({ params: Promise.resolve({ locale: "en", moduleId: MODULE_ID }) }),
    ).resolves.toEqual({ title: "en:pageTitle" });
  });
});
