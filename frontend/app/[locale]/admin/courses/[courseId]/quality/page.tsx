import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import { getTranslations } from "next-intl/server";
import { QualityClient } from "@/components/admin/quality/quality-client";

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string; courseId: string }>;
}) {
  await params;
  const t = await getTranslations("Admin.qualityAgent");
  return {
    title: t("pageTitle"),
    description: t("pageDescription"),
  };
}

export default async function AdminCourseQualityPage({
  params,
}: {
  params: Promise<{ locale: string; courseId: string }>;
}) {
  const { courseId } = await params;
  const t = await getTranslations("Admin.qualityAgent");

  return (
    <div className="flex flex-col flex-1 min-h-0">
      <div className="border-b bg-background p-4 shrink-0">
        <Link
          href="/admin/courses"
          className="mb-2 inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft className="size-4" />
          {t("backToCourses")}
        </Link>
        <h1 className="text-2xl font-bold">{t("pageTitle")}</h1>
        <p className="text-muted-foreground mt-1">{t("pageDescription")}</p>
      </div>
      <QualityClient courseId={courseId} />
    </div>
  );
}
