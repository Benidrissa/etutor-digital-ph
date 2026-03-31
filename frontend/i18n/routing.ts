import { defineRouting } from "next-intl/routing";
import { createNavigation } from "next-intl/navigation";

export const routing = defineRouting({
  locales: ["fr", "en"],
  defaultLocale: "fr",
  localeDetection: true,
});

// Create and export locale-aware navigation utilities
export const { Link, redirect, usePathname, useRouter } = createNavigation(routing);
