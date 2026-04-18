import { getTranslations } from "next-intl/server";
import { QBankAccessibleListClient } from "./client";

export default async function QBankTopLevelPage() {
  const t = await getTranslations("qbank");
  return (
    <div className="container mx-auto max-w-4xl space-y-6 p-4 md:p-6">
      <header>
        <h1 className="text-2xl font-semibold">{t("accessibleTitle")}</h1>
        <p className="text-sm text-muted-foreground">{t("accessibleSubtitle")}</p>
      </header>
      <QBankAccessibleListClient />
    </div>
  );
}
