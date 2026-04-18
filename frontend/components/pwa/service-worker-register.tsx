"use client";

import { useEffect } from "react";

/**
 * Registers /sw.js (built by @serwist/next from frontend/sw.ts) on mount.
 *
 * Mounted once inside the locale layout. The SW is the only path to offline
 * content caching + background sync — see issue #1615 for the regression this
 * fixes (the standalone build shipped without an SW registration call).
 */
export function ServiceWorkerRegister() {
  useEffect(() => {
    if (typeof window === "undefined") return;
    if (!("serviceWorker" in navigator)) return;
    // Don't register in dev — @serwist/next disables the build there too.
    if (process.env.NODE_ENV === "development") return;

    navigator.serviceWorker
      .register("/sw.js", { scope: "/" })
      .catch((err) => {
        // Log but don't fail the page — offline mode degrades gracefully.
        console.warn("[sw] registration failed:", err);
      });
  }, []);

  return null;
}
