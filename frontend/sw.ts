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
// v6 added an ExpirationPlugin to the pages cache, pre-warmed by
// frontend/lib/offline/prewarm.ts (PAGES_CACHE_NAME constant must
// match `pages-${CACHE_VERSION}`) so downloaded modules render offline.
// v7 excludes /api/v1/content/status/ from the API SWR cache so a stale
// "generating" body can't keep the quiz spinner alive forever offline.
// v8 drops api-responses-v7 entries that may hold answer-bearing summative
// quiz GET bodies cached before the server started stripping the answer
// key (#2550).
// v9 drops the pre-#2622 shell so existing PWA clients pick up the moved
// API Keys route (/admin/api-keys) + admin nav change instead of the stale
// cached settings-embedded card (#2625).
// v10 adds the story media route (#2681): story art, prop pictures and
// course figures go to their own stable cache, and the story player with
// props and the Previous button (#2682) replaces the cached one.
// v11 replaces the v10 story player, whose Previous handed out fresh first
// tries (#2688), and course figures get a cache of their own.
const CACHE_VERSION = "v11-story-fixes";

// Story pictures (#2681): character poses, backdrops, prop stickers and
// photos. Not versioned with CACHE_VERSION on purpose, so a downloaded story
// keeps its pictures across service worker updates. Course figures have a
// cache of their own, so browsing lesson figures never pushes story art out.
const STORY_MEDIA_CACHE = "story-media-v1";
const COURSE_FIGURES_CACHE = "course-figures-v1";
const STORY_MEDIA_PATH = /^\/api\/v1\/(story-art|story-props)\/[0-9a-f][0-9a-f-]{7,63}\/data$/i;
const SOURCE_IMAGE_PATH = /^\/api\/v1\/source-images\/[0-9a-f][0-9a-f-]{7,63}\/data$/i;

/** Only whole, successful answers are kept: never an error page. */
const okOnly = {
  cacheWillUpdate: async ({ response }: { response: Response }) =>
    response && response.status === 200 ? response : null,
};

// Least recently used goes first, and the 90 days count from the last use:
// story art is fetched once and then read from the cache for good, so
// counting from the first fetch would evict a story played every day (#2688).
const storyMediaPlugins = [
  new ExpirationPlugin({
    maxEntries: 600,
    maxAgeSeconds: 90 * DAY_IN_SECONDS,
    maxAgeFrom: "last-used",
    purgeOnQuotaError: true,
  }),
  okOnly,
];
const courseFigurePlugins = [
  new ExpirationPlugin({
    maxEntries: 200,
    maxAgeSeconds: 90 * DAY_IN_SECONDS,
    maxAgeFrom: "last-used",
    purgeOnQuotaError: true,
  }),
  okOnly,
];

/**
 * The runtime caches this worker versions with CACHE_VERSION. The first
 * service worker named them without a version ("pages", "static-assets"…).
 */
const VERSIONED_RUNTIME_CACHES = ["google-fonts", "static-images", "static-assets", "api-responses", "pages"];

/**
 * Runtime caches of an older CACHE_VERSION, or of the first, unversioned
 * worker (#2692): nothing reads them any more. Only names of this list
 * qualify, so the precache, the story media, the course figures and any
 * cache this worker does not own are kept by construction.
 */
export function isStaleRuntimeCache(name: string): boolean {
  const ours = VERSIONED_RUNTIME_CACHES.some((prefix) => name === prefix || name.startsWith(`${prefix}-v`));
  return ours && !name.endsWith(`-${CACHE_VERSION}`);
}

const OFFLINE_FALLBACK_URL = "/offline.html";

const serwist = new Serwist({
  // `/offline.html` is auto-injected into __SW_MANIFEST by @serwist/next from
  // public/. Re-adding it here with a different revision throws
  // `add-to-cache-list-conflicting-entries` at SW eval, which broke
  // registration end-to-end (see #2113).
  precacheEntries: self.__SW_MANIFEST || [],
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
    // Before the API rule: story art and prop pictures never change in place
    // (a new picture gets a new id), so the cache answers first.
    {
      matcher: ({ url, request }: { url: URL; request: Request }) =>
        request.method === "GET" && STORY_MEDIA_PATH.test(url.pathname),
      handler: new CacheFirst({
        cacheName: STORY_MEDIA_CACHE,
        plugins: storyMediaPlugins,
      }),
    },
    // Course figures have been fixed in place before: shown from the cache,
    // refreshed behind it, in a cache of their own.
    {
      matcher: ({ url, request }: { url: URL; request: Request }) =>
        request.method === "GET" && SOURCE_IMAGE_PATH.test(url.pathname),
      handler: new StaleWhileRevalidate({
        cacheName: COURSE_FIGURES_CACHE,
        plugins: courseFigurePlugins,
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
        // Same class as #1908: SWR serves the stale conversation list
        // after a delete, so the deleted row appears to come back.
        if (url.pathname.startsWith("/api/v1/tutor/")) return false;
        // Same class as #1908: after a backend status flip (e.g. #2125
        // unlocking modules), SWR serves the cached "locked" body and
        // learners still see the old gating UI.
        if (url.pathname.startsWith("/api/v1/progress/")) return false;
        // Per-task transient state for Celery generation. SWR replaying
        // a stale "generating" body keeps the quiz spinner alive forever
        // when the device is offline.
        if (url.pathname.startsWith("/api/v1/content/status/")) return false;
        // Story mode: a module story is gated per learner, rewritten when
        // any of its lessons or quizzes changes, and its offline copy lives
        // in IndexedDB (saved by the module download). SWR would replay a
        // regenerated, or no longer authorised, story for up to a day.
        if (url.pathname.startsWith("/api/v1/story-courses/")) return false;
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
        plugins: [
          new ExpirationPlugin({
            maxEntries: 60,
            maxAgeSeconds: 30 * DAY_IN_SECONDS,
            purgeOnQuotaError: true,
          }),
        ],
      }),
    },
  ],
});

// Each CACHE_VERSION bump used to leave the older runtime caches on the
// device for good (their expiration is no longer registered), until a quota
// error purged the live ones instead (#2688). The precache, the story media
// and the course figures are kept.
if (typeof self.addEventListener === "function") {
  self.addEventListener("activate", (event: ExtendableEvent) => {
    event.waitUntil(
      caches
        .keys()
        .then((keys) => Promise.all(keys.filter(isStaleRuntimeCache).map((key) => caches.delete(key))))
        .catch(() => undefined),
    );
  });
}

serwist.addEventListeners();
