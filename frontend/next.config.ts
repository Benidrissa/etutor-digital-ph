import type { NextConfig } from "next";
import createNextIntlPlugin from "next-intl/plugin";
import { withSentryConfig } from "@sentry/nextjs";
import { PHASE_DEVELOPMENT_SERVER, PHASE_PRODUCTION_BUILD } from "next/constants";

const withNextIntl = createNextIntlPlugin("./i18n/request.ts");

const nextConfig: NextConfig = {
  output: "standalone",
};

const configFn = async (phase: string) => {
  if (phase === PHASE_DEVELOPMENT_SERVER || phase === PHASE_PRODUCTION_BUILD) {
    const withSerwist = (await import("@serwist/next")).default({
      swSrc: "sw.ts",
      swDest: "public/sw.js",
      disable: false,
    });
    return withSentryConfig(withSerwist(withNextIntl(nextConfig)), {
      org: process.env.SENTRY_ORG,
      project: process.env.SENTRY_PROJECT,
      authToken: process.env.SENTRY_AUTH_TOKEN,
      silent: !process.env.CI,
      sourcemaps: {
        deleteSourcemapsAfterUpload: true,
      },
      tunnelRoute: "/monitoring",
    });
  }
  return withSentryConfig(withNextIntl(nextConfig), {
    org: process.env.SENTRY_ORG,
    project: process.env.SENTRY_PROJECT,
    authToken: process.env.SENTRY_AUTH_TOKEN,
    silent: !process.env.CI,
    sourcemaps: {
      deleteSourcemapsAfterUpload: true,
    },
    tunnelRoute: "/monitoring",
  });
};

export default configFn;
