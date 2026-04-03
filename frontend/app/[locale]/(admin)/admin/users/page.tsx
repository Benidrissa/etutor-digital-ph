import { getTranslations } from "next-intl/server";
import type { Metadata } from "next";

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>;
}): Promise<Metadata> {
  const { locale } = await params;
  const t = await getTranslations({ locale, namespace: "Admin" });
  return { title: t("users") };
}

export default async function AdminUsersPage() {
  const t = await getTranslations("Admin");

  return (
    <div className="container mx-auto px-4 py-8 max-w-5xl">
      <h1 className="text-2xl font-bold mb-2">{t("users")}</h1>
      <p className="text-sm text-muted-foreground mb-6">{t("usersDescription")}</p>
    </div>
  );
}
