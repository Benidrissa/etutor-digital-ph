import { Metadata } from "next";
import { getTranslations } from "next-intl/server";

import { StoryWeek } from "./story-week";

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string; slug: string }>;
}): Promise<Metadata> {
  const { locale } = await params;
  const t = await getTranslations({ locale, namespace: "Story" });

  return {
    title: t("catalogTitle"),
  };
}

export default async function StoryWeekPage({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = await params;
  return <StoryWeek slug={slug} />;
}
