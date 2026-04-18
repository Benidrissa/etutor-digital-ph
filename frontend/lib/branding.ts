export interface Branding {
  app_name: string;
  app_short_name: string;
  app_description_fr: string;
  app_description_en: string;
  tagline_fr: string;
  tagline_en: string;
  theme_color: string;
}

export const DEFAULT_BRANDING: Branding = {
  app_name: "Sira",
  app_short_name: "Sira",
  app_description_fr: "Plateforme d'apprentissage adaptative",
  app_description_en: "Adaptive learning platform",
  tagline_fr: "Apprenez à votre rythme",
  tagline_en: "Learn at your own pace",
  theme_color: "#22c55e",
};

/**
 * Server-side branding fetch used in generateMetadata / manifest route.
 * Hits the backend via BACKEND_URL (internal container hostname) in SSR,
 * falls back to DEFAULT_BRANDING if the call fails or env is missing.
 */
export async function getServerBranding(): Promise<Branding> {
  const backendUrl = process.env.BACKEND_URL;
  if (!backendUrl) return DEFAULT_BRANDING;
  try {
    const res = await fetch(`${backendUrl}/api/v1/settings/public`, {
      next: { revalidate: 300 },
    });
    if (!res.ok) return DEFAULT_BRANDING;
    const data = (await res.json()) as { branding?: Partial<Branding> };
    return { ...DEFAULT_BRANDING, ...(data.branding ?? {}) };
  } catch {
    return DEFAULT_BRANDING;
  }
}
