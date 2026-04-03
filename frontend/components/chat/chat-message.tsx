'use client';

import { useTranslations } from 'next-intl';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import remarkMath from 'remark-math';
import rehypeKatex from 'rehype-katex';
import { cn } from '@/lib/utils';

export interface ChatSource {
  title: string;
  chapter?: number;
  page?: number;
}

export interface ChatMessage {
  id: string;
  content: string;
  isUser: boolean;
  timestamp: Date;
  sources?: ChatSource[];
  isStreaming?: boolean;
}

interface ChatMessageProps {
  message: ChatMessage;
}

export function ChatMessage({ message }: ChatMessageProps) {
  const t = useTranslations('ChatTutor');

  return (
    <div
      className={cn(
        'flex w-full mb-4',
        message.isUser ? 'justify-end' : 'justify-start'
      )}
    >
      <div
        className={cn(
          'max-w-[85%] sm:max-w-[75%] rounded-lg p-3 shadow-sm',
          message.isUser
            ? 'bg-primary text-primary-foreground ml-4'
            : 'bg-muted mr-4'
        )}
      >
        {/* Message content */}
        <div className="text-sm leading-relaxed">
          {message.isUser ? (
            <>
              {message.content}
              {message.isStreaming && (
                <span className="inline-block w-2 h-4 ml-1 bg-current animate-pulse" />
              )}
            </>
          ) : (
            <div className="prose prose-sm max-w-none prose-p:my-1 prose-headings:mt-3 prose-headings:mb-1 prose-ul:my-1 prose-ol:my-1 prose-li:my-0.5 prose-blockquote:my-2 prose-pre:my-2 prose-table:text-xs [&_table]:w-full [&_table]:border-collapse [&_th]:border [&_th]:border-current/20 [&_th]:px-2 [&_th]:py-1 [&_td]:border [&_td]:border-current/20 [&_td]:px-2 [&_td]:py-1 overflow-x-auto">
              <ReactMarkdown remarkPlugins={[remarkGfm, remarkMath]} rehypePlugins={[rehypeKatex]}>
                {message.content}
              </ReactMarkdown>
              {message.isStreaming && (
                <span className="inline-block w-2 h-4 ml-1 bg-current animate-pulse" />
              )}
            </div>
          )}
        </div>

        {/* Sources */}
        {message.sources && message.sources.length > 0 && (
          <div className="mt-2 pt-2 border-t border-current/20">
            <div className="text-xs font-medium opacity-75 mb-1">
              {t('sources.title')}:
            </div>
            <div className="flex flex-wrap gap-1">
              {message.sources.map((source, index) => (
                <button
                  key={index}
                  className="text-xs px-2 py-1 rounded-md bg-current/10 hover:bg-current/20 transition-colors"
                  onClick={() => {
                    // TODO: Navigate to source material
                    console.log('Navigate to source:', source);
                  }}
                >
                  {source.title}
                  {source.chapter && ` - ${t('sources.chapter', { chapter: source.chapter })}`}
                  {source.page && `, ${t('sources.page', { page: source.page })}`}
                </button>
              ))}
            </div>
          </div>
        )}

        {/* Timestamp */}
        <div
          className={cn(
            'text-xs opacity-60 mt-1',
            message.isUser ? 'text-right' : 'text-left'
          )}
        >
          {message.timestamp.toLocaleTimeString([], {
            hour: '2-digit',
            minute: '2-digit'
          })}
        </div>
      </div>
    </div>
  );
}