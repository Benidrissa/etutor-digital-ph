import type { NextConfig } from "next";
import createNextIntlPlugin from "next-intl/plugin";
import { withSentryConfig } from "@sentry/nextjs";
import createBundleAnalyzer from "@next/bundle-analyzer";

const withNextIntl = createNextIntlPlugin("./i18n/request.ts");
const withBundleAnalyzer = createBundleAnalyzer({
  enabled: process.env.ANALYZE === "true",
});

const nextConfig: NextConfig = {
  output: "standalone",

  images: {
    formats: ["image/avif", "image/webp"],
    minimumCacheTTL: 60 * 60 * 24 * 30,
    deviceSizes: [320, 420, 640, 750, 828, 1080, 1200],
    imageSizes: [16, 32, 48, 64, 96, 128, 256],
    remotePatterns: [
      {
        protocol: "http",
        hostname: "localhost",
        port: "8000",
        pathname: "/api/**",
      },
      {
        protocol: "https",
        hostname: "**.fly.dev",
        pathname: "/api/**",
      },
      {
        protocol: "https",
        hostname: "**.railway.app",
        pathname: "/api/**",
      },
      {
        protocol: "https",
        hostname: "api.elearning.portfolio2.kimbetien.com",
        pathname: "/api/**",
      },
    ],
  },

  experimental: {
    optimizePackageImports: [
      "lucide-react",
      "@radix-ui/react-label",
      "@radix-ui/react-slot",
      "react-markdown",
      "rehype-katex",
      "remark-gfm",
      "remark-math",
    ],
  },

  async headers() {
    return [
      {
        source: "/(.*)",
        headers: [
          {
            key: "X-Content-Type-Options",
            value: "nosniff",
          },
          {
            key: "X-Frame-Options",
            value: "DENY",
          },
          {
            key: "X-XSS-Protection",
            value: "1; mode=block",
          },
        ],
      },
      {
        source: "/.well-known/assetlinks.json",
        headers: [
          {
            key: "Content-Type",
            value: "application/json",
          },
          {
            key: "Cache-Control",
            value: "public, max-age=86400",
          },
        ],
      },
      {
        source: "/static/(.*)",
        headers: [
          {
            key: "Cache-Control",
            value: "public, max-age=31536000, immutable",
          },
        ],
      },
      {
        source: "/_next/static/(.*)",
        headers: [
          {
            key: "Cache-Control",
            value: "public, max-age=31536000, immutable",
          },
        ],
      },
    ];
  },
};

export default withSentryConfig(
  withBundleAnalyzer(withNextIntl(nextConfig)),
  {
    org: process.env.SENTRY_ORG,
    project: process.env.SENTRY_PROJECT,
    authToken: process.env.SENTRY_AUTH_TOKEN,
    silent: !process.env.CI,
    sourcemaps: {
      deleteSourcemapsAfterUpload: true,
    },
    tunnelRoute: "/monitoring",
  }
);
