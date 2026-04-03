import type { NextConfig } from "next";
import createNextIntlPlugin from "next-intl/plugin";
import { withSentryConfig } from "@sentry/nextjs";

const withNextIntl = createNextIntlPlugin("./i18n/request.ts");

const nextConfig: NextConfig = {
  output: "standalone",
};

const withSerwist =
  process.env.NODE_ENV !== "test"
    ? (await import("@serwist/next")).default({
        swSrc: "sw.ts",
        swDest: "public/sw.js",
        reloadOnOnline: true,
        disable: process.env.NODE_ENV === "development",
      })
    : (config: NextConfig) => config;

export default withSentryConfig(withNextIntl(withSerwist(nextConfig)), {
  org: process.env.SENTRY_ORG,
  project: process.env.SENTRY_PROJECT,
  authToken: process.env.SENTRY_AUTH_TOKEN,
  silent: !process.env.CI,
  sourcemaps: {
    deleteSourcemapsAfterUpload: true,
  },
  tunnelRoute: "/monitoring",
});
