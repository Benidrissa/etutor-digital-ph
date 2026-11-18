/**
 * The breadcrumb the (app) layout shows on every page from md up: every
 * segment it names is translated, the module story route included.
 */

import { render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, describe, expect, it, vi } from "vitest";

import enMessages from "@/messages/en.json";
import frMessages from "@/messages/fr.json";

import { BreadcrumbNav } from "./breadcrumb-nav";

const MODULE_ID = "6f1c2d3e-1111-4222-8333-444455556666";

const pathname = vi.hoisted(() => ({ current: "/" }));

vi.mock("next/navigation", () => ({ usePathname: () => pathname.current }));

vi.mock("@/lib/api", () => ({
  getModuleDetailWithProgress: vi.fn().mockResolvedValue({
    title_fr: "Hygiène",
    title_en: "Hygiene",
  }),
}));

function renderAt(locale: "fr" | "en", path: string) {
  pathname.current = path;
  return render(
    <NextIntlClientProvider locale={locale} messages={locale === "fr" ? frMessages : enMessages}>
      <BreadcrumbNav />
    </NextIntlClientProvider>,
  );
}

beforeEach(() => {
  pathname.current = "/";
});

describe("BreadcrumbNav", () => {
  it.each([
    ["fr", "Hygiène", "Histoire"],
    ["en", "Hygiene", "Story"],
  ] as const)("names the module story page in %s", async (locale, moduleTitle, crumb) => {
    const { container } = renderAt(locale, `/${locale}/modules/${MODULE_ID}/story`);

    // The module's title resolves first, then the story crumb is the current page.
    expect(await screen.findByText(moduleTitle)).toBeInTheDocument();
    const current = container.querySelector('[aria-current="page"]');
    expect(current).toHaveTextContent(crumb);
    expect(current?.textContent?.trim()).toBe(crumb);
  });
});
