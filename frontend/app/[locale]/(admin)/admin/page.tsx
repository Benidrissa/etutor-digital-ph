import { getTranslations } from "next-intl/server";
import type { Metadata } from "next";

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>;
}): Promise<Metadata> {
  const { locale } = await params;
  const t = await getTranslations({ locale, namespace: "Admin" });
  return { title: t("title") };
}

export default async function AdminPage({
  params,
}: {
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  const t = await getTranslations({ locale, namespace: "Admin" });

  return (
    <div className="container mx-auto px-4 py-8 max-w-5xl">
      <h1 className="text-2xl font-bold mb-6">{t("title")}</h1>
      <div className="grid gap-4 md:grid-cols-2">
        <a
          href="admin/users"
          className="block rounded-lg border bg-card p-6 shadow-sm hover:bg-accent transition-colors"
        >
          <h2 className="text-lg font-semibold mb-1">{t("users")}</h2>
          <p className="text-sm text-muted-foreground">{t("usersDescription")}</p>
        </a>
      </div>
    </div>
  );
}
