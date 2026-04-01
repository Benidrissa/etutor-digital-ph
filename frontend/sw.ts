import type { PrecacheEntry, SerwistGlobalConfig } from "serwist";
import { Serwist, CacheFirst, StaleWhileRevalidate, NetworkFirst } from "serwist";

declare global {
  interface WorkerGlobalScope extends SerwistGlobalConfig {
    __SW_MANIFEST: (PrecacheEntry | string)[] | undefined;
  }
}

declare const self: ServiceWorkerGlobalScope;

const serwist = new Serwist({
  precacheEntries: self.__SW_MANIFEST,
  skipWaiting: true,
  clientsClaim: true,
  navigationPreload: true,
  runtimeCaching: [
    {
      matcher: /^https:\/\/fonts\.(?:googleapis|gstatic)\.com\/.*/i,
      handler: new CacheFirst({
        cacheName: "google-fonts",
        plugins: [
          {
            cacheWillUpdate: async ({ response }) => {
              if (response && response.status === 200) return response;
              return null;
            },
          },
        ],
      }),
    },
    {
      matcher: /\.(?:png|jpg|jpeg|svg|gif|webp|ico)$/i,
      handler: new CacheFirst({
        cacheName: "images",
      }),
    },
    {
      matcher: /\.(?:js|css)$/i,
      handler: new StaleWhileRevalidate({
        cacheName: "static-assets",
      }),
    },
    {
      matcher: ({ url }) => {
        return url.pathname.startsWith("/api/v1/") && !url.pathname.includes("/generate");
      },
      handler: new StaleWhileRevalidate({
        cacheName: "api-responses",
        plugins: [
          {
            cacheWillUpdate: async ({ response }) => {
              if (response && response.status === 200) return response;
              return null;
            },
          },
        ],
      }),
    },
    {
      matcher: ({ url }) => {
        return !url.pathname.startsWith("/api/") && !url.pathname.startsWith("/monitoring");
      },
      handler: new NetworkFirst({
        cacheName: "pages",
        networkTimeoutSeconds: 3,
      }),
    },
  ],
});

serwist.addEventListeners();
