import { ExpertGuard } from "@/components/expert/expert-guard";
import { ExpertNav } from "@/components/expert/expert-nav";
import { BottomNav } from "@/components/layout/bottom-nav";
import { Header } from "@/components/layout/header";
import { Sidebar } from "@/components/layout/sidebar";

export default function ExpertLayout({ children }: { children: React.ReactNode }) {
  return (
    <ExpertGuard>
      <div className="flex h-dvh flex-col md:flex-row">
        <Sidebar />
        <div className="flex flex-1 flex-col min-h-0">
          <Header />
          <ExpertNav />
          <main className="flex flex-col flex-1 overflow-y-auto pb-16 pt-0 md:pb-0">
            {children}
          </main>
        </div>
        <BottomNav />
      </div>
    </ExpertGuard>
  );
}
