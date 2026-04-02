/**
 * Locale detection utilities for SantePublique
 * Handles browser language detection and localStorage preferences
 */

export type Locale = "fr" | "en";

const SUPPORTED_LOCALES: Locale[] = ["fr", "en"];
const DEFAULT_LOCALE: Locale = "fr";
const STORAGE_KEY = "preferred-locale";

/**
 * Get the user's preferred locale from localStorage
 */
export function getStoredLocale(): Locale | null {
  if (typeof window === "undefined") return null;
  
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    return stored && SUPPORTED_LOCALES.includes(stored as Locale) 
      ? (stored as Locale) 
      : null;
  } catch {
    return null;
  }
}

/**
 * Save the user's locale preference to localStorage
 */
export function storeLocale(locale: Locale): void {
  if (typeof window === "undefined") return;
  
  try {
    localStorage.setItem(STORAGE_KEY, locale);
  } catch {
    // Fail silently if localStorage is not available
  }
}

/**
 * Detect the user's preferred locale based on:
 * 1. localStorage preference (highest priority)
 * 2. Browser language
 * 3. Default locale (fallback)
 */
export function detectPreferredLocale(): Locale {
  // Check localStorage first
  const storedLocale = getStoredLocale();
  if (storedLocale) {
    return storedLocale;
  }

  // Check browser language
  if (typeof window !== "undefined" && navigator.language) {
    const browserLang = navigator.language.split("-")[0].toLowerCase();
    if (SUPPORTED_LOCALES.includes(browserLang as Locale)) {
      return browserLang as Locale;
    }
  }

  // Fallback to default
  return DEFAULT_LOCALE;
}

/**
 * Check if a locale is supported
 */
export function isValidLocale(locale: string): locale is Locale {
  return SUPPORTED_LOCALES.includes(locale as Locale);
}