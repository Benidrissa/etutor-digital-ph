import type { PrecacheEntry, SerwistGlobalConfig } from "serwist";
import {
  Serwist,
  NetworkFirst,
  CacheFirst,
  StaleWhileRevalidate,
  ExpirationPlugin,
} from "serwist";

declare global {
  interface WorkerGlobalScope extends SerwistGlobalConfig {
    __SW_MANIFEST: (PrecacheEntry | string)[] | undefined;
  }
}

declare const self: ServiceWorkerGlobalScope;

const DAY_IN_SECONDS = 24 * 60 * 60;

// Bump when storage shape or routing changes so clients drop stale caches.
const CACHE_VERSION = "v2-canonical-unit-number";

const OFFLINE_FALLBACK_URL = "/offline.html";

const serwist = new Serwist({
  precacheEntries: [
    ...(self.__SW_MANIFEST || []),
    { url: OFFLINE_FALLBACK_URL, revision: "1" },
  ],
  skipWaiting: true,
  clientsClaim: true,
  navigationPreload: false,
  fallbacks: {
    entries: [
      {
        url: OFFLINE_FALLBACK_URL,
        matcher: ({ request }: { request: Request }) => request.mode === "navigate",
      },
    ],
  },
  runtimeCaching: [
    {
      matcher: /^https:\/\/fonts\.(googleapis|gstatic)\.com\/.*/i,
      handler: new CacheFirst({
        cacheName: `google-fonts-${CACHE_VERSION}`,
        plugins: [
          new ExpirationPlugin({
            maxEntries: 30,
            maxAgeSeconds: 365 * DAY_IN_SECONDS,
          }),
          {
            cacheWillUpdate: async ({ response }: { response: Response }) => {
              if (response && response.status === 200) return response;
              return null;
            },
            cacheKeyWillBeUsed: async ({ request }: { request: Request }) => request,
          },
        ],
      }),
    },
    {
      matcher: /\.(?:png|jpg|jpeg|svg|gif|webp|ico)$/i,
      handler: new CacheFirst({
        cacheName: `static-images-${CACHE_VERSION}`,
        plugins: [
          new ExpirationPlugin({
            maxEntries: 100,
            maxAgeSeconds: 30 * DAY_IN_SECONDS,
          }),
        ],
      }),
    },
    {
      matcher: /\.(?:js|css|woff2|woff|ttf|eot)$/i,
      handler: new CacheFirst({
        cacheName: `static-assets-${CACHE_VERSION}`,
        plugins: [
          new ExpirationPlugin({
            maxEntries: 200,
            maxAgeSeconds: 30 * DAY_IN_SECONDS,
          }),
        ],
      }),
    },
    {
      matcher: ({ url, request }: { url: URL; request: Request }) => {
        if (request.method !== "GET") return false;
        if (url.pathname.startsWith("/api/generate")) return false;
        // Don't cache user-mutable profile/auth state — SWR would serve
        // stale bodies after PATCH and the form re-syncs to old values
        // (#1908).
        if (url.pathname.startsWith("/api/v1/users/")) return false;
        if (url.pathname.startsWith("/api/v1/auth/")) return false;
        if (url.pathname.startsWith("/api/")) return true;
        return false;
      },
      handler: new StaleWhileRevalidate({
        cacheName: `api-responses-${CACHE_VERSION}`,
        plugins: [
          new ExpirationPlugin({
            maxEntries: 50,
            maxAgeSeconds: DAY_IN_SECONDS,
          }),
        ],
      }),
    },
    {
      matcher: ({ request }: { request: Request }) => request.mode === "navigate",
      handler: new NetworkFirst({
        cacheName: `pages-${CACHE_VERSION}`,
        networkTimeoutSeconds: 3,
      }),
    },
  ],
});

serwist.addEventListeners();
