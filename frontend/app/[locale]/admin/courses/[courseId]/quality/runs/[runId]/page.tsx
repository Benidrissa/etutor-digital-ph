import { getTranslations } from "next-intl/server";
import { RunDetailClient } from "@/components/admin/quality/run-detail-client";

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string; courseId: string; runId: string }>;
}) {
  await params;
  const t = await getTranslations("Admin.qualityAgent.runDetail");
  return {
    title: t("pageTitle"),
    description: t("pageDescription"),
  };
}

export default async function AdminRunDetailPage({
  params,
}: {
  params: Promise<{ locale: string; courseId: string; runId: string }>;
}) {
  const { courseId, runId } = await params;
  const t = await getTranslations("Admin.qualityAgent.runDetail");

  return (
    <div className="flex flex-col flex-1 min-h-0">
      <div className="border-b bg-background p-4 shrink-0">
        <h1 className="text-2xl font-bold">{t("pageTitle")}</h1>
        <p className="text-muted-foreground mt-1">{t("pageDescription")}</p>
      </div>
      <RunDetailClient courseId={courseId} runId={runId} />
    </div>
  );
}
