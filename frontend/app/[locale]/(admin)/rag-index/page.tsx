import { getTranslations } from "next-intl/server";
import { RagIndexClient } from "./rag-index-client";

export default async function RagIndexPage() {
  const t = await getTranslations("Admin.RagIndex");

  return (
    <div>
      <h1 className="text-2xl font-semibold">{t("title")}</h1>
      <p className="mt-1 text-muted-foreground">{t("subtitle")}</p>
      <div className="mt-6">
        <RagIndexClient />
      </div>
    </div>
  );
}
