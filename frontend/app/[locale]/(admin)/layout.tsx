import { getTranslations } from "next-intl/server";
import Link from "next/link";

export default async function AdminLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const t = await getTranslations("Admin");

  return (
    <div className="flex min-h-dvh flex-col">
      <header className="border-b bg-background px-4 py-3 md:px-6">
        <div className="mx-auto flex max-w-5xl items-center gap-4">
          <Link href="/" className="text-sm text-muted-foreground hover:text-foreground">
            ← {t("backToApp")}
          </Link>
          <span className="text-muted-foreground">/</span>
          <span className="text-sm font-medium">{t("adminPanel")}</span>
        </div>
      </header>
      <main className="flex-1 px-4 py-6 md:px-6">
        <div className="mx-auto max-w-5xl">{children}</div>
      </main>
    </div>
  );
}
