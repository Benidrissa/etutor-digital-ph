import { AdminGuard } from "@/components/admin/admin-guard";
import { BottomNav } from "@/components/layout/bottom-nav";
import { Header } from "@/components/layout/header";
import { Sidebar } from "@/components/layout/sidebar";

export default function AdminLayout({ children }: { children: React.ReactNode }) {
  return (
    <AdminGuard>
      <div className="flex h-dvh flex-col md:flex-row">
        <Sidebar />
        <div className="flex flex-1 flex-col min-h-0">
          <Header />
          <main className="flex flex-col flex-1 overflow-y-auto pb-16 pt-0 md:pb-0">
            {children}
          </main>
        </div>
        <BottomNav />
      </div>
    </AdminGuard>
  );
}
