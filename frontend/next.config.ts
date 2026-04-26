import type { NextConfig } from "next";
import createNextIntlPlugin from "next-intl/plugin";
import { withSentryConfig } from "@sentry/nextjs";
import createBundleAnalyzer from "@next/bundle-analyzer";
import withSerwistInit from "@serwist/next";

const withNextIntl = createNextIntlPlugin("./i18n/request.ts");
const withBundleAnalyzer = createBundleAnalyzer({
  enabled: process.env.ANALYZE === "true",
});

// Wires sw.ts → /public/sw.js at build time. Required for PWA registration;
// without this the standalone build ships with no service worker and offline
// mode silently fails (see issue #1615).
const withSerwist = withSerwistInit({
  swSrc: "sw.ts",
  swDest: "public/sw.js",
  reloadOnOnline: true,
  disable: process.env.NODE_ENV === "development",
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
      // Production wildcard for tenants provisioned under *.sira-donnia.org.
      // Covers same-origin `<tenant>.tenant.sira-donnia.org/api/**` *and*
      // the direct `api.<tenant>.tenant.sira-donnia.org` subdomain.
      {
        protocol: "https",
        hostname: "**.sira-donnia.org",
        pathname: "/**",
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
    // Course-resource PDFs (tens of MB) are uploaded through the /api/* rewrite
    // to the FastAPI backend. Next.js's default proxy body buffer is 10MB,
    // which silently truncates larger uploads and makes the upstream return 502.
    // Match the wizard's advertised "max 100 Mo par fichier". See #2018.
    middlewareClientMaxBodySize: "100mb",
  },

  async rewrites() {
    const backend = process.env.BACKEND_URL || "http://backend:8000";
    return [
      { source: "/api/:path*", destination: `${backend}/api/:path*` },
    ];
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
  withSerwist(withBundleAnalyzer(withNextIntl(nextConfig))),
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
