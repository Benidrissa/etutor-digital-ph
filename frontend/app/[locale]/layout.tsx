import { NextIntlClientProvider } from "next-intl";
import { getMessages } from "next-intl/server";
import { notFound } from "next/navigation";
import { routing } from "@/i18n/routing";
import { QueryProvider } from "@/lib/query-provider";
import { SettingsProvider } from "@/lib/settings-context";
import { InstallPrompt } from "@/components/pwa/install-prompt";
import { ServiceWorkerRegister } from "@/components/pwa/service-worker-register";
import { PostHogProvider } from "@/lib/posthog-provider";

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

  return (
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
  );
}
