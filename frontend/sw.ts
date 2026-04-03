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

const serwist = new Serwist({
  precacheEntries: self.__SW_MANIFEST,
  skipWaiting: true,
  clientsClaim: true,
  navigationPreload: false,
  runtimeCaching: [
    {
      matcher: /^https:\/\/fonts\.(googleapis|gstatic)\.com\/.*/i,
      handler: new CacheFirst({
        cacheName: "google-fonts",
        plugins: [
          new ExpirationPlugin({
            maxEntries: 30,
            maxAgeSeconds: 365 * DAY_IN_SECONDS,
          }),
          {
            cacheWillUpdate: async ({ response }) => {
              if (response && response.status === 200) return response;
              return null;
            },
            cacheKeyWillBeUsed: async ({ request }) => request,
          },
        ],
      }),
    },
    {
      matcher: /\.(?:png|jpg|jpeg|svg|gif|webp|ico)$/i,
      handler: new CacheFirst({
        cacheName: "static-images",
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
        cacheName: "static-assets",
        plugins: [
          new ExpirationPlugin({
            maxEntries: 200,
            maxAgeSeconds: 30 * DAY_IN_SECONDS,
          }),
        ],
      }),
    },
    {
      matcher: ({ url, request }) => {
        if (request.method !== "GET") return false;
        if (url.pathname.startsWith("/api/generate")) return false;
        if (url.pathname.startsWith("/api/")) return true;
        return false;
      },
      handler: new StaleWhileRevalidate({
        cacheName: "api-responses",
        plugins: [
          new ExpirationPlugin({
            maxEntries: 50,
            maxAgeSeconds: DAY_IN_SECONDS,
          }),
        ],
      }),
    },
    {
      matcher: ({ request }) => request.mode === "navigate",
      handler: new NetworkFirst({
        cacheName: "pages",
        networkTimeoutSeconds: 3,
      }),
    },
  ],
});

serwist.addEventListeners();
