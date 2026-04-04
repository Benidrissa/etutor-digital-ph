import { getTranslations } from "next-intl/server";
import { CourseListClient } from "@/components/admin/course-list-client";

export async function generateMetadata() {
  const t = await getTranslations("AdminCourses");
  return {
    title: t("pageTitle"),
    description: t("pageDescription"),
  };
}

export default async function AdminCoursesPage() {
  const t = await getTranslations("AdminCourses");

  return (
    <div className="p-4 md:p-6">
      <div className="mb-6">
        <h1 className="text-2xl font-semibold">{t("pageTitle")}</h1>
        <p className="mt-1 text-muted-foreground">{t("pageDescription")}</p>
      </div>
      <CourseListClient />
    </div>
  );
}
