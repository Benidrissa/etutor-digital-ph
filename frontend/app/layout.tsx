import type { Metadata } from "next";
import { Inter, JetBrains_Mono } from "next/font/google";
import "./globals.css";
import "katex/dist/katex.min.css";
import { getServerBranding } from "@/lib/branding";

const inter = Inter({
  variable: "--font-sans",
  subsets: ["latin"],
  display: "swap",
  weight: ["400", "500", "600", "700"],
  preload: true,
});

const jetbrainsMono = JetBrains_Mono({
  variable: "--font-mono",
  subsets: ["latin"],
  display: "swap",
  weight: ["400", "500"],
  preload: false,
});

export async function generateMetadata(): Promise<Metadata> {
  const branding = await getServerBranding();
  return {
    title: {
      default: branding.app_name,
      template: `%s · ${branding.app_name}`,
    },
    description: branding.app_description_en,
    manifest: "/manifest.webmanifest",
    appleWebApp: {
      capable: true,
      statusBarStyle: "default",
      title: branding.app_short_name,
    },
    formatDetection: {
      telephone: false,
    },
    themeColor: branding.theme_color,
    viewport: {
      width: "device-width",
      initialScale: 1,
      maximumScale: 1,
      userScalable: false,
    },
  };
}

export default async function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  const branding = await getServerBranding();
  return (
    <html className={`${inter.variable} ${jetbrainsMono.variable}`}>
      <head>
        <link rel="apple-touch-startup-image" href="/icon-512x512.svg" />
        <meta name="apple-mobile-web-app-capable" content="yes" />
        <meta name="apple-mobile-web-app-status-bar-style" content="default" />
        <meta name="apple-mobile-web-app-title" content={branding.app_short_name} />
      </head>
      <body className="min-h-dvh bg-background font-sans text-foreground antialiased">
        {children}
      </body>
    </html>
  );
}
