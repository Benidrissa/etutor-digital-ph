import { Header } from "@/components/layout/header";
import { Sidebar } from "@/components/layout/sidebar";

export default function AdminLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-dvh flex-col md:flex-row">
      <Sidebar />
      <div className="flex flex-1 flex-col min-h-0">
        <Header />
        <main className="flex flex-col flex-1 min-h-0 pb-16 pt-0 md:pb-0">{children}</main>
      </div>
    </div>
  );
}
