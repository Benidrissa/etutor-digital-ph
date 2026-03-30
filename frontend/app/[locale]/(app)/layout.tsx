import { BottomNav } from "@/components/layout/bottom-nav";
import { Header } from "@/components/layout/header";
import { Sidebar } from "@/components/layout/sidebar";

export default function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-dvh flex-col md:flex-row">
      <Sidebar />
      <div className="flex flex-1 flex-col md:flex-row">
        <Header />
        <main className="flex-1 pb-16 pt-0 md:pb-0">{children}</main>
      </div>
      <BottomNav />
    </div>
  );
}
