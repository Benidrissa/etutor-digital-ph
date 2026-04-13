import { OrgProvider } from "@/components/org/org-context";
import { OrgGuard } from "@/components/org/org-guard";
import { OrgNav } from "@/components/org/org-nav";
import { Header } from "@/components/layout/header";

export default function OrgLayout({
  children,
  params,
}: {
  children: React.ReactNode;
  params: { orgSlug: string };
}) {
  return (
    <OrgProvider orgSlug={params.orgSlug}>
      <OrgGuard>
        <div className="flex h-dvh flex-col">
          <Header />
          <OrgNav />
          <main className="flex flex-col flex-1 overflow-y-auto p-4 md:p-6">
            {children}
          </main>
        </div>
      </OrgGuard>
    </OrgProvider>
  );
}
