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

  return (
    <>
      <FloatingChatButton onClick={openChat} />
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
      <div className="relative">
        {children}
        <ChatUIComponents />
      </div>
    </ChatProvider>
  );
}