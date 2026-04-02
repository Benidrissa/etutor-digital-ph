'use client';

import { ChatProvider, useChatContext, ChatPanel, FloatingChatButton } from '@/components/chat';
import { usePathname } from 'next/navigation';

function ChatUIComponents() {
  const { isOpen, openChat, closeChat } = useChatContext();
  const pathname = usePathname();
  
  // Extract moduleId from pathname if we're in a module page
  const moduleId = pathname.includes('/modules/') 
    ? pathname.split('/modules/')[1]?.split('/')[0]
    : undefined;

  // Hide floating button when already on the tutor page
  const isOnTutorPage = pathname.endsWith('/tutor');

  return (
    <>
      {!isOnTutorPage && <FloatingChatButton onClick={openChat} />}
      <ChatPanel 
        isOpen={isOpen} 
        onClose={closeChat}
        moduleId={moduleId}
      />
    </>
  );
}

interface ChatLayoutProps {
  children: React.ReactNode;
}

export function ChatLayout({ children }: ChatLayoutProps) {
  return (
    <ChatProvider>
      <div className="relative h-dvh overflow-hidden">
        {children}
        <ChatUIComponents />
      </div>
    </ChatProvider>
  );
}