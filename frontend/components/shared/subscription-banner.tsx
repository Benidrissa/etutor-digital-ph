"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { Link } from "@/i18n/routing";
import { apiFetch } from "@/lib/api";
import { X } from "lucide-react";

interface SubscriptionStatus {
  has_subscription: boolean;
  subscription_status?: string;
}

export function SubscriptionBanner() {
  const t = useTranslations("Subscribe");
  const [show, setShow] = useState(false);
  const [pending, setPending] = useState(false);

  useEffect(() => {
    // Don't show for admin
    try {
      const token = localStorage.getItem("access_token");
      if (token) {
        const payload = JSON.parse(atob(token.split(".")[1]));
        if (payload.role === "admin") return;
      }
    } catch {
      // ignore
    }

    // Check if dismissed this session
    if (sessionStorage.getItem("sub-banner-dismissed")) return;

    apiFetch<SubscriptionStatus>("/api/v1/subscriptions/me")
      .then((data) => {
        if (!data.has_subscription) {
          setShow(true);
        } else if (data.subscription_status === "pending_payment") {
          setPending(true);
          setShow(true);
        }
      })
      .catch(() => {});
  }, []);

  if (!show) return null;

  const dismiss = () => {
    sessionStorage.setItem("sub-banner-dismissed", "1");
    setShow(false);
  };

  return (
    <div className="bg-primary/10 border-b border-primary/20 px-4 py-2 flex items-center justify-between gap-2">
      <div className="flex items-center gap-2 min-w-0 flex-1">
        <span className="text-sm text-primary font-medium truncate">
          {pending ? t("pending") : t("banner")}
        </span>
        {!pending && (
          <Link
            href="/subscribe"
            className="shrink-0 rounded-md bg-primary px-3 py-1 text-xs font-medium text-white hover:bg-primary/90 transition-colors"
          >
            {t("bannerCTA")}
          </Link>
        )}
      </div>
      <button
        onClick={dismiss}
        className="shrink-0 p-1 rounded hover:bg-primary/10 transition-colors"
        aria-label="Dismiss"
      >
        <X className="h-4 w-4 text-primary/60" />
      </button>
    </div>
  );
}
