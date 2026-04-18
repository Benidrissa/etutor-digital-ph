import type { Metadata } from "next";
import { Inter, JetBrains_Mono } from "next/font/google";
import { NextIntlClientProvider } from "next-intl";
import { getMessages } from "next-intl/server";
import { notFound } from "next/navigation";
import { routing } from "@/i18n/routing";
import { QueryProvider } from "@/lib/query-provider";
import { SettingsProvider } from "@/lib/settings-context";
import { InstallPrompt } from "@/components/pwa/install-prompt";
import { ServiceWorkerRegister } from "@/components/pwa/service-worker-register";
import { PostHogProvider } from "@/lib/posthog-provider";
import { getServerBranding } from "@/lib/branding";
import "../globals.css";
import "katex/dist/katex.min.css";

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

export default async function LocaleLayout({
  children,
  params,
}: {
  children: React.ReactNode;
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;

  if (!routing.locales.includes(locale as "fr" | "en")) {
    notFound();
  }

  const messages = await getMessages();
  const branding = await getServerBranding();

  return (
    <html
      lang={locale}
      className={`${inter.variable} ${jetbrainsMono.variable}`}
    >
      <head>
        <link rel="apple-touch-startup-image" href="/icon-512x512.svg" />
        <meta name="apple-mobile-web-app-capable" content="yes" />
        <meta name="apple-mobile-web-app-status-bar-style" content="default" />
        <meta name="apple-mobile-web-app-title" content={branding.app_short_name} />
      </head>
      <body className="min-h-dvh bg-background font-sans text-foreground antialiased">
        <NextIntlClientProvider messages={messages}>
          <PostHogProvider>
            <QueryProvider>
              <SettingsProvider>
                {children}
                <InstallPrompt />
                <ServiceWorkerRegister />
              </SettingsProvider>
            </QueryProvider>
          </PostHogProvider>
        </NextIntlClientProvider>
      </body>
    </html>
  );
}
