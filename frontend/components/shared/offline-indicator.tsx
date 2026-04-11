"use client";

import { useEffect, useRef } from "react";
import { useTranslations } from "next-intl";
import { WifiOff, Wifi } from "lucide-react";
import { useNetworkStatus } from "@/lib/hooks/use-network-status";
import { SyncManager } from "@/lib/offline/sync-manager";

export function OfflineIndicator() {
  const t = useTranslations("Offline");
  const { isOnline, justReconnected } = useNetworkStatus();
  const syncTriggered = useRef(false);

  // Trigger background sync when reconnecting
  useEffect(() => {
    if (justReconnected && !syncTriggered.current) {
      syncTriggered.current = true;
      SyncManager.getInstance().syncNow();
    }
    if (!justReconnected) {
      syncTriggered.current = false;
    }
  }, [justReconnected]);

  if (isOnline && !justReconnected) return null;

  if (justReconnected) {
    return (
      <div
        role="status"
        aria-live="polite"
        className="flex items-center justify-center gap-2 bg-teal-600 px-4 py-2 text-sm font-medium text-white"
      >
        <Wifi className="h-4 w-4 shrink-0" aria-hidden="true" />
        <span>{t("reconnected")}</span>
      </div>
    );
  }

  return (
    <div
      role="status"
      aria-live="assertive"
      className="flex items-center justify-center gap-2 bg-amber-500 px-4 py-2 text-sm font-medium text-white"
    >
      <WifiOff className="h-4 w-4 shrink-0" aria-hidden="true" />
      <span>{t("offline")}</span>
    </div>
  );
}
