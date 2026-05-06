import { getTranslations } from "next-intl/server";
import { GlossaryClient } from "@/components/admin/quality/glossary-client";

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string; courseId: string }>;
}) {
  await params;
  const t = await getTranslations("Admin.qualityAgent.glossary");
  return {
    title: t("pageTitle"),
    description: t("pageDescription"),
  };
}

export default async function AdminGlossaryPage({
  params,
}: {
  params: Promise<{ locale: string; courseId: string }>;
}) {
  const { courseId } = await params;
  const t = await getTranslations("Admin.qualityAgent.glossary");

  return (
    <div className="flex flex-col flex-1 min-h-0">
      <div className="border-b bg-background p-4 shrink-0">
        <h1 className="text-2xl font-bold">{t("pageTitle")}</h1>
        <p className="text-muted-foreground mt-1">{t("pageDescription")}</p>
      </div>
      <GlossaryClient courseId={courseId} />
    </div>
  );
}
