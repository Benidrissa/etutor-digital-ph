import { getTranslations } from "next-intl/server";
import { UnitQualityClient } from "@/components/admin/quality/unit-quality-client";

export async function generateMetadata({
  params,
}: {
  params: Promise<{
    locale: string;
    courseId: string;
    runId: string;
    contentId: string;
  }>;
}) {
  await params;
  const t = await getTranslations("Admin.qualityAgent");
  return {
    title: t("unit.pageTitle"),
    description: t("unit.pageDescription"),
  };
}

export default async function AdminUnitQualityPage({
  params,
}: {
  params: Promise<{
    locale: string;
    courseId: string;
    runId: string;
    contentId: string;
  }>;
}) {
  const { courseId, runId, contentId } = await params;
  const t = await getTranslations("Admin.qualityAgent");

  return (
    <div className="flex flex-col flex-1 min-h-0">
      <div className="border-b bg-background p-4 shrink-0">
        <h1 className="text-2xl font-bold">{t("unit.pageTitle")}</h1>
        <p className="text-muted-foreground mt-1">{t("unit.pageDescription")}</p>
      </div>
      <UnitQualityClient courseId={courseId} runId={runId} contentId={contentId} />
    </div>
  );
}
