"use client";

import posthog from "posthog-js";
import { PostHogProvider as PHProvider, usePostHog } from "posthog-js/react";
import { useEffect, type ReactNode } from "react";
import { usePathname, useSearchParams } from "next/navigation";

if (typeof window !== "undefined" && process.env.NEXT_PUBLIC_POSTHOG_KEY) {
  // Respect user opt-out preference
  const optedOut = localStorage.getItem("analytics_opt_out") === "1";

  posthog.init(process.env.NEXT_PUBLIC_POSTHOG_KEY, {
    opt_out_capturing_by_default: optedOut,
    api_host:
      process.env.NEXT_PUBLIC_POSTHOG_HOST || "https://eu.i.posthog.com",

    // Privacy-first: no cookies, honor DNT, no IP capture
    persistence: "localStorage",
    disable_cookie: true,
    respect_dnt: true,
    ip: false,

    // No session recording (privacy + bundle size)
    disable_session_recording: true,

    // Only explicit events, no autocapture
    autocapture: false,
    mask_all_text: true,
    mask_all_element_attributes: true,

    // Manual pageview capture for SPA routing
    capture_pageview: false,
    capture_pageleave: true,

    // Lightweight: no feature flags polling
    advanced_disable_feature_flags: true,
    advanced_disable_decide: true,
  });
}

function PostHogPageview() {
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const ph = usePostHog();

  useEffect(() => {
    if (pathname && ph) {
      let url = window.origin + pathname;
      if (searchParams?.toString()) {
        url = url + "?" + searchParams.toString();
      }
      // Pseudonymize UUIDs in path
      const cleanPath = pathname.replace(
        /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/gi,
        ":id"
      );
      ph.capture("$pageview", { $current_url: url, clean_path: cleanPath });
    }
  }, [pathname, searchParams, ph]);

  return null;
}

export function PostHogProvider({ children }: { children: ReactNode }) {
  if (!process.env.NEXT_PUBLIC_POSTHOG_KEY) {
    return <>{children}</>;
  }

  return (
    <PHProvider client={posthog}>
      <PostHogPageview />
      {children}
    </PHProvider>
  );
}
