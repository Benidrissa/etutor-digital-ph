import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import { QBankTestsDiscoveryClient } from "./client";

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>;
}): Promise<Metadata> {
  const { locale } = await params;
  const t = await getTranslations({ locale, namespace: "qbank" });
  return { title: t("testsDiscoveryTitle") };
}

export default function QBankTestsDiscoveryPage() {
  return <QBankTestsDiscoveryClient />;
}
