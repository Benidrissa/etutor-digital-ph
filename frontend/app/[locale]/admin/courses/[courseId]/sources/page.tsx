import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import { getTranslations } from "next-intl/server";
import { CourseSourcesClient } from "@/components/admin/course-sources-client";

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string; courseId: string }>;
}) {
  await params;
  const t = await getTranslations("AdminCourses.sourcesPage");
  return {
    title: t("pageTitle"),
    description: t("pageDescription"),
  };
}

export default async function AdminCourseSourcesPage({
  params,
}: {
  params: Promise<{ locale: string; courseId: string }>;
}) {
  const { courseId } = await params;
  const t = await getTranslations("AdminCourses.sourcesPage");

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
      <div className="p-4">
        <CourseSourcesClient courseId={courseId} />
      </div>
    </div>
  );
}
