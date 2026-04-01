"use client";

import { useEffect, useState } from "react";

export interface NetworkStatus {
  isOnline: boolean;
  justReconnected: boolean;
}

export function useNetworkStatus(): NetworkStatus {
  const [isOnline, setIsOnline] = useState<boolean>(
    typeof navigator !== "undefined" ? navigator.onLine : true
  );
  const [justReconnected, setJustReconnected] = useState(false);

  useEffect(() => {
    let reconnectedTimer: ReturnType<typeof setTimeout> | null = null;

    function handleOnline() {
      setIsOnline(true);
      setJustReconnected(true);
      reconnectedTimer = setTimeout(() => {
        setJustReconnected(false);
      }, 4000);
    }

    function handleOffline() {
      setIsOnline(false);
      setJustReconnected(false);
      if (reconnectedTimer) {
        clearTimeout(reconnectedTimer);
        reconnectedTimer = null;
      }
    }

    window.addEventListener("online", handleOnline);
    window.addEventListener("offline", handleOffline);

    return () => {
      window.removeEventListener("online", handleOnline);
      window.removeEventListener("offline", handleOffline);
      if (reconnectedTimer) clearTimeout(reconnectedTimer);
    };
  }, []);

  return { isOnline, justReconnected };
}
