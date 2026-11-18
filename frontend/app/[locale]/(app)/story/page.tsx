import { Metadata } from "next";
import { getTranslations } from "next-intl/server";

import { StoryCatalog } from "./story-catalog";

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>;
}): Promise<Metadata> {
  const { locale } = await params;
  const t = await getTranslations({ locale, namespace: "Story" });

  return {
    title: t("catalogTitle"),
    description: t("catalogDescription"),
  };
}

export default async function StoryCoursesPage() {
  return <StoryCatalog />;
}
