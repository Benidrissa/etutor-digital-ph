import { BottomNav } from "@/components/layout/bottom-nav";
import { Header } from "@/components/layout/header";
import { Sidebar } from "@/components/layout/sidebar";
import { BreadcrumbNav } from "@/components/layout/breadcrumb-nav";
import { ChatLayout } from "@/components/chat/chat-layout";
import { SyncStatusIndicator } from "@/components/shared/sync-status-indicator";

export default function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    <ChatLayout>
      <div className="flex min-h-dvh flex-col md:flex-row">
        <Sidebar />
        <div className="flex flex-1 flex-col">
          <Header />
          <BreadcrumbNav />
          <div className="flex items-center justify-end px-4 py-1">
            <SyncStatusIndicator />
          </div>
          <main className="flex-1 pb-16 pt-0 md:pb-0">{children}</main>
        </div>
        <BottomNav />
      </div>
    </ChatLayout>
  );
}
