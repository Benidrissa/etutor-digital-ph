import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>;
}): Promise<Metadata> {
  const { locale } = await params;
  const t = await getTranslations({ locale, namespace: "Courses" });
  return { title: t("title") };
}

export default function CoursesLayout({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}
