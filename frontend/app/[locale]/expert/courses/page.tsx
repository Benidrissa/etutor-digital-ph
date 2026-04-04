import { getTranslations } from "next-intl/server";

export default async function ExpertCoursesPage() {
  const t = await getTranslations("ExpertNav");

  return (
    <div className="p-4 md:p-6">
      <h1 className="text-2xl font-semibold">{t("courses")}</h1>
    </div>
  );
}
