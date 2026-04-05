import { BottomNav } from "@/components/layout/bottom-nav";
import { Header } from "@/components/layout/header";
import { Sidebar } from "@/components/layout/sidebar";
import { BreadcrumbNav } from "@/components/layout/breadcrumb-nav";
import { ChatLayout } from "@/components/chat/chat-layout";
import { OfflineIndicator } from "@/components/shared/offline-indicator";
import { AuthGuard } from "@/components/shared/auth-guard";

export default function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    <AuthGuard>
      <ChatLayout>
        <div className="flex h-dvh flex-col md:flex-row">
          <Sidebar />
          <div className="flex flex-1 flex-col min-h-0">
            <OfflineIndicator />
            <Header />
            <BreadcrumbNav />
            <main className="flex flex-col flex-1 overflow-y-auto pb-16 pt-0 md:pb-0">{children}</main>
          </div>
          <BottomNav />
        </div>
      </ChatLayout>
    </AuthGuard>
  );
}
