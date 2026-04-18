"use client";

import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { getPublicConfig } from "./api";
import { DEFAULT_BRANDING, type Branding } from "./branding";

interface SettingsContextValue {
  settings: Record<string, unknown>;
  branding: Branding;
  loading: boolean;
  getSetting: <T = unknown>(key: string, fallback: T) => T;
}

const SettingsContext = createContext<SettingsContextValue>({
  settings: {},
  branding: DEFAULT_BRANDING,
  loading: true,
  getSetting: (_key, fallback) => fallback,
});

export function SettingsProvider({ children }: { children: ReactNode }) {
  const [settings, setSettings] = useState<Record<string, unknown>>({});
  const [branding, setBranding] = useState<Branding>(DEFAULT_BRANDING);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    getPublicConfig()
      .then(({ settings, branding }) => {
        setSettings(settings);
        setBranding(branding);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  function getSetting<T = unknown>(key: string, fallback: T): T {
    const val = settings[key];
    return val !== undefined ? (val as T) : fallback;
  }

  return (
    <SettingsContext.Provider value={{ settings, branding, loading, getSetting }}>
      {children}
    </SettingsContext.Provider>
  );
}

export function useSettings() {
  return useContext(SettingsContext);
}

export function useBranding(): Branding {
  return useContext(SettingsContext).branding;
}
