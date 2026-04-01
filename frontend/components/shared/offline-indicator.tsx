"use client";

import { useTranslations } from "next-intl";
import { WifiOff, Wifi } from "lucide-react";
import { useNetworkStatus } from "@/lib/hooks/use-network-status";

export function OfflineIndicator() {
  const t = useTranslations("Offline");
  const { isOnline, justReconnected } = useNetworkStatus();

  if (isOnline && !justReconnected) return null;

  if (!isOnline) {
    return (
      <div
        role="status"
        aria-live="polite"
        className="flex min-h-10 items-center justify-center gap-2 bg-amber-500 px-4 py-2 text-sm font-medium text-white"
      >
        <WifiOff className="h-4 w-4 flex-shrink-0" aria-hidden="true" />
        <span>{t("offline")}</span>
      </div>
    );
  }

  return (
    <div
      role="status"
      aria-live="polite"
      className="flex min-h-10 animate-pulse items-center justify-center gap-2 bg-teal-600 px-4 py-2 text-sm font-medium text-white"
    >
      <Wifi className="h-4 w-4 flex-shrink-0" aria-hidden="true" />
      <span>{t("reconnected")}</span>
    </div>
  );
}
