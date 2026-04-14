"use client";

import { useParams } from "next/navigation";
import { OrgProvider } from "@/components/org/org-context";
import { OrgGuard } from "@/components/org/org-guard";
import { OrgNav } from "@/components/org/org-nav";
import { Header } from "@/components/layout/header";
import { Sidebar } from "@/components/layout/sidebar";
import { BottomNav } from "@/components/layout/bottom-nav";

export default function OrgLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const params = useParams<{ orgSlug: string }>();
  const orgSlug = params.orgSlug;

  return (
    <OrgProvider orgSlug={orgSlug}>
      <OrgGuard>
        <div className="flex h-dvh flex-col md:flex-row">
          <Sidebar />
          <div className="flex flex-1 flex-col min-h-0">
            <Header />
            <OrgNav />
            <main className="flex flex-col flex-1 overflow-y-auto pb-16 pt-0 md:pb-0 p-4 md:p-6">
              {children}
            </main>
          </div>
          <BottomNav />
        </div>
      </OrgGuard>
    </OrgProvider>
  );
}
