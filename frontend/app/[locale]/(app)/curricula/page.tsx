import { getTranslations } from "next-intl/server";
import { CurriculaTopLevelClient } from "./client";

export default async function CurriculaTopLevelPage() {
  const t = await getTranslations("Navigation");
  return (
    <div className="container mx-auto max-w-4xl space-y-6 p-4 md:p-6">
      <header>
        <h1 className="text-2xl font-semibold">{t("curricula")}</h1>
        <p className="text-sm text-muted-foreground">{t("curriculaDescription")}</p>
      </header>
      <CurriculaTopLevelClient />
    </div>
  );
}
