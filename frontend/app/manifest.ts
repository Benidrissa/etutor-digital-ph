import type { MetadataRoute } from "next";
import { getServerBranding } from "@/lib/branding";

export default async function manifest(): Promise<MetadataRoute.Manifest> {
  const branding = await getServerBranding();
  return {
    name: branding.app_name,
    short_name: branding.app_short_name,
    description: branding.app_description_en,
    start_url: "/",
    display: "standalone",
    background_color: "#ffffff",
    theme_color: branding.theme_color,
    orientation: "portrait-primary",
    scope: "/",
    categories: ["education"],
    icons: [
      { src: "/icon-192x192.png", sizes: "192x192", type: "image/png", purpose: "any" },
      { src: "/icon-512x512.png", sizes: "512x512", type: "image/png", purpose: "any" },
      { src: "/icon-192x192.png", sizes: "192x192", type: "image/png", purpose: "maskable" },
      { src: "/icon-512x512.png", sizes: "512x512", type: "image/png", purpose: "maskable" },
      { src: "/icon-192x192.svg", sizes: "192x192", type: "image/svg+xml" },
      { src: "/icon-512x512.svg", sizes: "512x512", type: "image/svg+xml" },
    ],
  };
}
