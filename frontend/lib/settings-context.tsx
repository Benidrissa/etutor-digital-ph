"use client";

import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { getPublicSettings } from "./api";

interface SettingsContextValue {
  settings: Record<string, unknown>;
  loading: boolean;
  getSetting: <T = unknown>(key: string, fallback: T) => T;
}

const SettingsContext = createContext<SettingsContextValue>({
  settings: {},
  loading: true,
  getSetting: (_key, fallback) => fallback,
});

export function SettingsProvider({ children }: { children: ReactNode }) {
  const [settings, setSettings] = useState<Record<string, unknown>>({});
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    getPublicSettings()
      .then(setSettings)
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  function getSetting<T = unknown>(key: string, fallback: T): T {
    const val = settings[key];
    return val !== undefined ? (val as T) : fallback;
  }

  return (
    <SettingsContext.Provider value={{ settings, loading, getSetting }}>
      {children}
    </SettingsContext.Provider>
  );
}

export function useSettings() {
  return useContext(SettingsContext);
}
