'use client';

import { useState, useEffect, useRef, useCallback } from 'react';
import { useTranslations, useLocale } from 'next-intl';
import { track } from '@/lib/analytics';
import { Link } from '@/i18n/routing';
import { X, MoreVertical, Trash2, Menu, HelpCircle, BookOpen, GraduationCap, ChevronDown, Globe } from 'lucide-react';
import { getMyEnrollments, type CourseWithEnrollment, API_BASE } from '@/lib/api';
import { Button } from '@/components/ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import { ChatMessage as ChatMessageComponent, type ChatMessage } from './chat-message';
import { ChatInput } from './chat-input';
import { ChatSuggestions } from './chat-suggestions';
import { VoiceCallModal } from './voice-call-modal';
import { TypingIndicator } from './typing-indicator';
import { UsageCounter } from './usage-counter';
import { ChatSkeleton } from './chat-skeleton';
import { cn } from '@/lib/utils';
import { authClient, AuthError } from '@/lib/auth';
import { useRouter, usePathname } from 'next/navigation';
import {
  fetchConversation,
  fetchTutorStats,
  getOfflineConversation,
  invalidateConversationCache,
  invalidateConversationsCache,
  deleteConversation as apiDeleteConversation,
  clearDraft,
  clearStaleDrafts,
} from '@/lib/tutor-api';

interface ChatPanelProps {
  isOpen: boolean;
  onClose: () => void;
  moduleId?: string;
  courseId?: string;
  conversationId?: string | null;
  className?: string;
  embedded?: boolean;
  onConversationCreated?: (conversationId: string) => void;
  // Fires after every message round-trip (the SSE `finished` chunk lands).
  // The parent uses it to re-fetch the conversation list so the sidebar
  // message count updates in real time (#1978).
  onMessageSent?: (conversationId: string) => void;
  onOpenConversations?: () => void;
}

export function ChatPanel({
  isOpen,
  onClose,
  moduleId,
  courseId,
  conversationId,
  className,
  embedded = false,
  onConversationCreated,
  onMessageSent,
  onOpenConversations,
}: ChatPanelProps) {
  const t = useTranslations('ChatTutor');
  const locale = useLocale();
  const router = useRouter();
  const pathname = usePathname();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [isHistoryLoading, setIsHistoryLoading] = useState(false);
  const [isTyping, setIsTyping] = useState(false);
  const [showClearDialog, setShowClearDialog] = useState(false);
  const [showVoiceCall, setShowVoiceCall] = useState(false);
  const [currentUsage, setCurrentUsage] = useState(0);
  const [maxDailyUsage, setMaxDailyUsage] = useState(200);
  const [limitReached, setLimitReached] = useState(false);
  const [activeConversationId, setActiveConversationId] = useState<string | null>(
    conversationId ?? null
  );
  const [tutorMode, setTutorMode] = useState<'socratic' | 'explanatory'>(() => {
    if (typeof window !== 'undefined') {
      return (localStorage.getItem('tutorMode') as 'socratic' | 'explanatory') || 'socratic';
    }
    return 'socratic';
  });
  const scrollAreaRef = useRef<HTMLDivElement>(null);
  const abortControllerRef = useRef<AbortController | null>(null);
  const isMountedRef = useRef(true);
  const [enrolledCourses, setEnrolledCourses] = useState<CourseWithEnrollment[]>([]);
  // Per-thread course context (#YRyXI). The previous implementation kept a
  // single global `activeCourseId` in localStorage, so picking a course in
  // one thread silently overwrote every other thread. Initial value comes
  // from the prop (set by the parent from the selected conversation's
  // ``course_id``); when no prop is passed we wait for the conversation
  // fetch below or fall back to the first enrollment for brand-new threads.
  const [activeCourseId, setActiveCourseId] = useState<string | null>(courseId ?? null);

  const isLimitReached = currentUsage >= maxDailyUsage;

  const activeCourse = enrolledCourses.find((c) => c.id === activeCourseId);
  const activeCourseLabel = activeCourse
    ? (locale === 'fr' ? activeCourse.title_fr : activeCourse.title_en)
    : null;

  const welcomeMessage: ChatMessage = {
    id: 'welcome',
    content: t('welcomeMessage'),
    isUser: false,
    timestamp: new Date(),
  };

  useEffect(() => {
    localStorage.setItem('tutorMode', tutorMode);
  }, [tutorMode]);

  // Reflect prop-driven course changes (parent passes a different conversation
  // → the per-thread course_id). Without this the dropdown would stick to
  // whichever course the previous thread declared (#YRyXI).
  useEffect(() => {
    if (courseId) setActiveCourseId(courseId);
  }, [courseId]);

  // Fetch enrolled courses for course selector. Skip for anonymous visitors
  // so /courses (public catalog) doesn't fire a 401 into every visitor's
  // console (#1622) — there's nothing to enroll-list for logged-out users.
  const refreshEnrolledCourses = useCallback(async () => {
    if (!authClient.isAuthenticated()) return;
    try {
      const courses = await getMyEnrollments({ orderBy: 'last_accessed', limit: 3 });
      setEnrolledCourses(courses);
      // Only fall back to the first enrolled course when the thread itself
      // has no course context yet (brand-new conversation, no prop). For
      // existing threads the per-conversation course_id loaded in the
      // history-fetch effect below is the source of truth (#YRyXI).
      setActiveCourseId((current) => {
        if (current && courses.some((c) => c.id === current)) return current;
        if (current) return current;
        return courses[0]?.id ?? null;
      });
    } catch {
      // silent — matches prior behavior
    }
  }, []);

  useEffect(() => {
    refreshEnrolledCourses();
  }, [refreshEnrolledCourses]);

  // Server-truth refresh for daily message quota. Re-called on any failure
  // path in handleSendMessage so the optimistic +1 increment is reconciled
  // against `/tutor/remaining` when the assistant container is suppressed.
  const refetchRemaining = useCallback(async () => {
    if (!authClient.isAuthenticated()) return;
    try {
      const stats = await fetchTutorStats();
      if (!isMountedRef.current) return;
      setMaxDailyUsage(stats.daily_messages_limit);
      setCurrentUsage(stats.daily_messages_used);
    } catch {
      // silent — anonymous visitors and transient failures are handled upstream
    }
  }, []);

  useEffect(() => {
    refetchRemaining();
  }, [refetchRemaining]);

  useEffect(() => {
    isMountedRef.current = true;
    return () => {
      isMountedRef.current = false;
      abortControllerRef.current?.abort();
    };
  }, []);

  // Abort any in-flight stream when the user switches conversations so the
  // optimistic usage increment from the abandoned send gets rolled back via
  // the catch/finally path instead of hanging until unmount.
  useEffect(() => {
    return () => {
      abortControllerRef.current?.abort();
    };
  }, [activeConversationId]);

  useEffect(() => {
    clearStaleDrafts();
  }, []);

  useEffect(() => {
    setActiveConversationId(conversationId ?? null);
  }, [conversationId]);

  useEffect(() => {
    if (!activeConversationId) {
      setMessages([welcomeMessage]);
      return;
    }

    setIsHistoryLoading(true);
    fetchConversation(activeConversationId)
      .then((conv) => {
        // Restore per-thread course context (#YRyXI). The dropdown reads
        // from `activeCourseId`, so loading a thread must reset it to that
        // thread's stored course rather than leaking the previous thread's
        // selection. Skip when the parent already supplied a `courseId`
        // prop (in-context launches like the lesson-page side panel).
        if (!courseId && conv.course_id) {
          setActiveCourseId(conv.course_id);
        }
        const loaded: ChatMessage[] = conv.messages.map((m, i) => ({
          id: `history-${i}`,
          content: m.content,
          isUser: m.role === 'user',
          timestamp: new Date(m.timestamp),
          sources: m.sources?.map((s, j) => ({
            title: s.source ?? String(j + 1),
            chapter: s.chapter ?? j + 1,
            page: s.page ?? 0,
          })),
          // Voice output (#1932): listen button needs (conversationId, index).
          messageIndex: m.role === 'assistant' ? i : undefined,
          conversationId:
            m.role === 'assistant' ? activeConversationId : undefined,
          // Source-image markers (#1937): backend resolves on GET so history
          // messages render images identically to the live stream.
          sourceImageRefs: m.source_image_refs,
        }));
        setMessages(loaded.length > 0 ? loaded : [welcomeMessage]);
      })
      .catch(() => {
        const offline = getOfflineConversation(activeConversationId);
        if (offline) {
          const loaded: ChatMessage[] = offline.messages.map((m, i) => ({
            id: `offline-${i}`,
            content: m.content,
            isUser: m.role === 'user',
            timestamp: new Date(m.timestamp),
            sources: m.sources?.map((s, j) => ({
              title: s.source ?? String(j + 1),
              chapter: s.chapter ?? j + 1,
              page: s.page ?? 0,
            })),
            messageIndex: m.role === 'assistant' ? i : undefined,
            conversationId:
              m.role === 'assistant' ? activeConversationId : undefined,
            sourceImageRefs: m.source_image_refs,
          }));
          setMessages(loaded.length > 0 ? loaded : [welcomeMessage]);
        } else {
          setMessages([welcomeMessage]);
        }
      })
      .finally(() => setIsHistoryLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeConversationId]);

  useEffect(() => {
    if (scrollAreaRef.current) {
      const scrollArea = scrollAreaRef.current;
      scrollArea.scrollTop = scrollArea.scrollHeight;
    }
  }, [messages, isTyping]);

  const handleSendMessage = async (messageContent: string, attachedFiles: import('./chat-input').AttachedFileInfo[] = []) => {
    if (isLimitReached || isLoading) return;

    const userMessage: ChatMessage = {
      id: Date.now().toString(),
      content: messageContent,
      isUser: true,
      timestamp: new Date(),
      attachedFiles: attachedFiles.length > 0 ? attachedFiles : undefined,
    };

    setMessages((prev) => [...prev, userMessage]);
    setCurrentUsage((prev) => prev + 1);
    setIsLoading(true);
    setIsTyping(true);
    track('tutor_message_sent', {
      module_id: moduleId ?? '',
      language: locale,
    });

    // Pre-empt the localStorage cache as soon as the user sends, not just on
    // the 'finished' SSE chunk. A dropped stream used to leave the cache
    // serving the pre-message snapshot — and once the backend persists the
    // user message early (#1975), that stale cache would re-hide it on next
    // mount. Invalidate now so any later refetch goes to network.
    if (activeConversationId) {
      invalidateConversationCache(activeConversationId);
    }

    abortControllerRef.current?.abort();
    const abortController = new AbortController();
    abortControllerRef.current = abortController;
    let usageReconciled = false;

    try {
      let token: string;
      try {
        token = await authClient.getValidToken();
      } catch (err) {
        if (err instanceof AuthError && err.status === 401) {
          router.push('/login');
          return;
        }
        throw err;
      }
      const response = await fetch(`${API_BASE}/api/v1/tutor/chat`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({
          message: messageContent,
          conversation_id: activeConversationId ?? null,
          course_id: activeCourseId ?? null,
          module_id: moduleId ?? null,
          tutor_mode: tutorMode,
          file_ids: attachedFiles.map((f) => f.fileId),
          locale: locale,
        }),
        signal: abortController.signal,
      });

      if (!response.ok) {
        if (response.status === 401) {
          router.push('/login');
          return;
        }
        throw new Error(`API error: ${response.status}`);
      }

      const reader = response.body?.getReader();
      const decoder = new TextDecoder();
      let fullContent = '';
      const aiMessageId = (Date.now() + 1).toString();

      setMessages((prev) => [
        ...prev,
        {
          id: aiMessageId,
          content: '',
          isUser: false,
          timestamp: new Date(),
        },
      ]);

      if (reader) {
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          const text = decoder.decode(value, { stream: true });
          const lines = text.split('\n');

          for (const line of lines) {
            if (!line.startsWith('data: ')) continue;
            try {
              const chunk = JSON.parse(line.slice(6));
              if (chunk.type === 'conversation_id' && chunk.data?.conversation_id) {
                const newConvId = chunk.data.conversation_id as string;
                if (!activeConversationId) {
                  setActiveConversationId(newConvId);
                  onConversationCreated?.(newConvId);
                }
              } else if (chunk.type === 'content' && chunk.data?.text) {
                fullContent += chunk.data.text;
                setMessages((prev) =>
                  prev.map((m) => (m.id === aiMessageId ? { ...m, content: fullContent } : m))
                );
              } else if (chunk.type === 'sources_cited' && chunk.data?.sources) {
                setMessages((prev) =>
                  prev.map((m) =>
                    m.id === aiMessageId
                      ? {
                          ...m,
                          sources: chunk.data.sources.map(
                            (
                              s: { source: string; chapter?: number; page?: number },
                              i: number
                            ) => ({
                              title: s.source ?? String(i + 1),
                              chapter: s.chapter ?? i + 1,
                              page: s.page ?? 0,
                            })
                          ),
                        }
                      : m
                  )
                );
              } else if (chunk.type === 'source_image_refs' && chunk.data?.refs) {
                setMessages((prev) =>
                  prev.map((m) =>
                    m.id === aiMessageId
                      ? { ...m, sourceImageRefs: chunk.data.refs }
                      : m
                  )
                );
              } else if (
                chunk.type === 'message_complete' &&
                typeof chunk.data?.message_index === 'number' &&
                chunk.conversation_id
              ) {
                const msgIndex = chunk.data.message_index as number;
                const convId = chunk.conversation_id as string;
                setMessages((prev) =>
                  prev.map((m) =>
                    m.id === aiMessageId
                      ? { ...m, messageIndex: msgIndex, conversationId: convId }
                      : m
                  )
                );
              } else if (chunk.type === 'finished' && chunk.data?.conversation_id) {
                const finishedConvId = chunk.data.conversation_id as string;
                invalidateConversationCache(finishedConvId);
                invalidateConversationsCache();
                // Tell the sidebar to re-fetch so the per-conversation
                // message count updates within the same render cycle (#1978).
                // Cache invalidation alone isn't enough because the parent
                // never re-fetches on its own.
                onMessageSent?.(finishedConvId);
                void refreshEnrolledCourses();
                if (typeof chunk.data?.remaining_messages === 'number') {
                  const remaining = chunk.data.remaining_messages as number;
                  setCurrentUsage(maxDailyUsage - remaining);
                  usageReconciled = true;
                }
              } else if (chunk.type === 'error') {
                const errorCode = chunk.data?.code;
                fullContent =
                  errorCode === 'limit_reached' ? t('errorLimitReached') : t('error');
                if (errorCode === 'limit_reached') {
                  setLimitReached(true);
                }
                setMessages((prev) =>
                  prev.map((m) =>
                    m.id === aiMessageId ? { ...m, content: fullContent } : m
                  )
                );
                // Backend persists the user message before the LLM loop runs
                // (#1975), so any error other than limit_reached (which fails
                // before persist) leaves a new row in the sidebar that needs
                // a refresh — without this the count stays stale until the
                // user sends another message. (#1978)
                if (errorCode !== 'limit_reached' && chunk.conversation_id) {
                  invalidateConversationsCache();
                  onMessageSent?.(chunk.conversation_id as string);
                }
              }
            } catch {
              // Skip unparseable lines
            }
          }
        }
      }
    } catch (error) {
      if ((error as Error | undefined)?.name !== 'AbortError') {
        console.error('Failed to send message:', error);
        if (isMountedRef.current) {
          setMessages((prev) => [
            ...prev,
            {
              id: (Date.now() + 1).toString(),
              content: t('error'),
              isUser: false,
              timestamp: new Date(),
            },
          ]);
        }
      }
    } finally {
      if (abortControllerRef.current === abortController) {
        abortControllerRef.current = null;
      }
      // Reconcile the optimistic +1 from line 229 whenever the response
      // container was suppressed (error chunk, non-ok response, thrown
      // fetch, or user-initiated abort via conversation switch / unmount).
      // Backend only persists the user message together with a successful
      // assistant reply, so without this the counter drifts high.
      if (!usageReconciled && isMountedRef.current) {
        setCurrentUsage((prev) => Math.max(0, prev - 1));
        void refetchRemaining();
      }
      if (isMountedRef.current) {
        setIsLoading(false);
        setIsTyping(false);
      }
    }
  };

  const handleSuggestionClick = (suggestion: string) => {
    if (!isLimitReached && !isLoading) {
      handleSendMessage(suggestion, []);
    }
  };

  const handleClearHistory = async () => {
    if (activeConversationId) {
      try {
        await apiDeleteConversation(activeConversationId);
      } catch { /* proxy may block response */ }
      clearDraft(activeConversationId);
    }
    clearDraft(null);
    setMessages([welcomeMessage]);
    setActiveConversationId(null);
    setShowClearDialog(false);
    onConversationCreated?.('');  // Signal parent to refresh list
  };

  if (!isOpen) return null;

  return (
    <>
      <div
        className={cn(
          embedded
            ? 'flex flex-col h-full w-full bg-background'
            : cn(
                'fixed inset-0 z-50 flex flex-col bg-background',
                'md:relative md:inset-auto md:w-96 md:border-l',
                'transition-transform duration-300 ease-in-out',
                isOpen ? 'translate-x-0' : 'translate-x-full md:translate-x-0'
              ),
          className
        )}
      >
        {/* Header */}
        <div className="flex items-center justify-between p-3 border-b bg-background shrink-0 gap-2 flex-nowrap">
          <div className="flex items-center gap-2 shrink-0">
            {onOpenConversations && (
              <Button
                variant="ghost"
                size="icon"
                onClick={onOpenConversations}
                className="h-11 w-11 md:hidden"
                aria-label={t('openConversations')}
              >
                <Menu className="h-5 w-5" />
              </Button>
            )}
            <h2 className="text-base font-semibold whitespace-nowrap">{t('title')}</h2>
          </div>
          <div className="flex items-center gap-1 min-w-0">
            {enrolledCourses.length > 1 ? (
              <DropdownMenu>
                <DropdownMenuTrigger>
                  <Button variant="outline" size="sm" className="h-9 max-w-[160px] gap-1 text-xs">
                    <GraduationCap className="h-3.5 w-3.5 shrink-0" />
                    <span className="truncate">{activeCourseLabel || t('title')}</span>
                    <ChevronDown className="h-3 w-3 shrink-0" />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                  {enrolledCourses.map((course) => (
                    <DropdownMenuItem
                      key={course.id}
                      onClick={() => setActiveCourseId(course.id)}
                      className={course.id === activeCourseId ? 'bg-accent' : ''}
                    >
                      {locale === 'fr' ? course.title_fr : course.title_en}
                    </DropdownMenuItem>
                  ))}
                </DropdownMenuContent>
              </DropdownMenu>
            ) : activeCourseLabel ? (
              <span className="text-xs text-muted-foreground truncate max-w-[160px] flex items-center gap-1">
                <GraduationCap className="h-3.5 w-3.5 shrink-0" />
                {activeCourseLabel}
              </span>
            ) : null}
            {/* Voice-call button hidden until voice tutor has proper RAG
                grounding (#1960). Backend endpoints stay live so existing
                in-flight sessions complete cleanly. */}
            <Button
              variant={tutorMode === 'socratic' ? 'default' : 'outline'}
              size="sm"
              onClick={() => setTutorMode(tutorMode === 'socratic' ? 'explanatory' : 'socratic')}
              className="h-9 gap-1.5 text-xs"
              title={tutorMode === 'socratic' ? t('modeSocraticTooltip') : t('modeExplanatoryTooltip')}
            >
              {tutorMode === 'socratic' ? (
                <><HelpCircle className="h-3.5 w-3.5" /><span className="hidden sm:inline">{t('modeSocratic')}</span></>
              ) : (
                <><BookOpen className="h-3.5 w-3.5" /><span className="hidden sm:inline">{t('modeExplanatory')}</span></>
              )}
            </Button>
            <DropdownMenu>
              <DropdownMenuTrigger>
                <Button variant="ghost" size="icon" className="h-11 w-11">
                  <MoreVertical className="h-4 w-4" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuItem
                  className="md:hidden"
                  onClick={() => {
                    const next = locale === 'fr' ? 'en' : 'fr';
                    router.push(pathname.replace(/^\/(fr|en)/, '/' + next));
                  }}
                >
                  <Globe className="h-4 w-4 mr-2" />
                  {locale === 'fr' ? 'English' : 'Français'}
                </DropdownMenuItem>
                <DropdownMenuItem onClick={() => setShowClearDialog(true)}>
                  <Trash2 className="h-4 w-4 mr-2" />
                  {t('clearHistory')}
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
            <Button
              variant="ghost"
              size="icon"
              onClick={onClose}
              className="h-11 w-11 md:hidden"
            >
              <X className="h-4 w-4" />
            </Button>
          </div>
        </div>

        {/* Usage Counter */}
        <UsageCounter
          currentUsage={currentUsage}
          maxUsage={maxDailyUsage}
          className="px-3 py-1"
        />

        {/* Messages */}
        <div className="flex-1 flex flex-col min-h-0">
          <div ref={scrollAreaRef} className="flex-1 overflow-y-auto px-3 py-2">
            {isHistoryLoading ? (
              <ChatSkeleton />
            ) : (
              <>
                {messages.map((message) => (
                  <ChatMessageComponent key={message.id} message={message} />
                ))}
                {isTyping && <TypingIndicator />}
              </>
            )}

            {messages.length === 0 && !isLoading && !isHistoryLoading && (
              <div className="flex flex-col items-center justify-center h-full text-center p-6">
                <div className="text-muted-foreground mb-2">{t('emptyState')}</div>
                <div className="text-sm text-muted-foreground">{t('emptyStateDescription')}</div>
              </div>
            )}
          </div>

          {!isLimitReached && !limitReached && (
            <ChatSuggestions onSuggestionClick={handleSuggestionClick} disabled={isLoading} />
          )}

          {(isLimitReached || limitReached) && (
            <div className="mx-3 mb-2 rounded-lg bg-primary/10 border border-primary/20 p-3 text-center">
              <p className="text-sm text-primary font-medium mb-2">
                {t('errorLimitReached')}
              </p>
              <Link
                href="/subscribe"
                className="inline-flex items-center rounded-md bg-primary px-4 py-2 text-xs font-medium text-white hover:bg-primary/90 transition-colors"
              >
                {t('upgradePrompt')}
              </Link>
            </div>
          )}

          <ChatInput
            key={activeConversationId ?? 'new'}
            onSendMessage={handleSendMessage}
            disabled={isLimitReached || limitReached || isLoading}
            conversationId={activeConversationId}
          />
        </div>
      </div>

      {/* Voice Call Modal */}
      <VoiceCallModal
        open={showVoiceCall}
        onOpenChange={setShowVoiceCall}
        courseId={activeCourseId}
        moduleId={moduleId ?? null}
      />

      {/* Clear History Dialog */}
      <AlertDialog open={showClearDialog} onOpenChange={setShowClearDialog}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t('confirmClearHistory')}</AlertDialogTitle>
            <AlertDialogDescription>
              {t('confirmClearHistoryDescription')}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t('cancel')}</AlertDialogCancel>
            <AlertDialogAction onClick={handleClearHistory}>
              {t('clearHistory')}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}
