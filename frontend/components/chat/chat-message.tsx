'use client';

import { useTranslations, useLocale } from 'next-intl';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import remarkMath from 'remark-math';
import rehypeKatex from 'rehype-katex';
import { cn } from '@/lib/utils';
import { AttachedFileCard } from '@/components/chat/file-preview';
import { SourceImage } from '@/components/learning/source-image';
import type { SourceImageMeta } from '@/lib/api';
import { splitWithSourceImageMarkers } from '@/lib/source-image-utils';

export interface ChatSource {
  title: string;
  chapter?: number;
  page?: number;
}

export interface AttachedFileInfo {
  fileId: string;
  name: string;
  mimeType: string;
  sizeBytes: number;
}

export interface ChatMessage {
  id: string;
  content: string;
  isUser: boolean;
  timestamp: Date;
  sources?: ChatSource[];
  isStreaming?: boolean;
  attachedFiles?: AttachedFileInfo[];
  sourceImageRefs?: SourceImageMeta[];
}

interface ChatMessageProps {
  message: ChatMessage;
}

const mdClass =
  'prose prose-sm max-w-none prose-p:my-0.5 prose-p:leading-snug prose-headings:mt-2 prose-headings:mb-1 prose-ul:my-0.5 prose-ol:my-0.5 prose-li:my-0 prose-blockquote:my-1 prose-pre:my-1 prose-table:text-xs [&_table]:w-full [&_table]:border-collapse [&_th]:border [&_th]:border-current/20 [&_th]:px-2 [&_th]:py-1 [&_td]:border [&_td]:border-current/20 [&_td]:px-2 [&_td]:py-1 overflow-x-auto';

export function ChatMessage({ message }: ChatMessageProps) {
  const t = useTranslations('ChatTutor');
  const locale = useLocale();
  const language = (locale === 'fr' ? 'fr' : 'en') as 'fr' | 'en';
  const hasFiles = message.attachedFiles && message.attachedFiles.length > 0;

  const imageMap = new Map<string, SourceImageMeta>(
    (message.sourceImageRefs ?? []).map((ref) => [ref.id, ref])
  );
  const hasImageMarkers =
    !message.isUser &&
    imageMap.size > 0 &&
    /\{\{source_image:[0-9a-f-]{36}\}\}/.test(message.content);

  function renderAiContent() {
    if (!hasImageMarkers) {
      return (
        <div className={mdClass}>
          <ReactMarkdown remarkPlugins={[remarkGfm, remarkMath]} rehypePlugins={[rehypeKatex]}>
            {message.content}
          </ReactMarkdown>
          {message.isStreaming && (
            <span className="inline-block w-2 h-4 ml-1 bg-current animate-pulse" />
          )}
        </div>
      );
    }

    const parts = splitWithSourceImageMarkers(message.content, imageMap);
    return (
      <>
        {parts.map((part, i) =>
          part.type === 'source_image' ? (
            <SourceImage key={i} {...part.meta} language={language} />
          ) : (
            <div key={i} className={mdClass}>
              <ReactMarkdown remarkPlugins={[remarkGfm, remarkMath]} rehypePlugins={[rehypeKatex]}>
                {part.text}
              </ReactMarkdown>
            </div>
          )
        )}
        {message.isStreaming && (
          <span className="inline-block w-2 h-4 ml-1 bg-current animate-pulse" />
        )}
      </>
    );
  }

  return (
    <div
      className={cn(
        'flex w-full mb-4',
        message.isUser ? 'justify-end' : 'justify-start'
      )}
    >
      <div
        className={cn(
          'rounded-lg p-3 shadow-sm',
          message.isUser
            ? 'bg-primary text-primary-foreground ml-4'
            : 'bg-muted mr-4'
        )}
      >
        {hasFiles && (
          <div className="flex flex-wrap gap-1.5 mb-2">
            {message.attachedFiles!.map((f) => (
              <AttachedFileCard
                key={f.fileId}
                name={f.name}
                mimeType={f.mimeType}
                sizeBytes={f.sizeBytes}
              />
            ))}
          </div>
        )}

        {hasFiles && message.isUser && message.attachedFiles!.some((f) => f.mimeType.startsWith('image/')) && (
          <div className="flex flex-wrap gap-1.5 mb-2">
            {message.attachedFiles!
              .filter((f) => f.mimeType.startsWith('image/'))
              .map((f) => (
                <div key={f.fileId} className="text-xs text-primary-foreground/70 italic">
                  🖼 {f.name}
                </div>
              ))}
          </div>
        )}

        <div className="text-sm leading-relaxed">
          {message.isUser ? (
            <>
              {message.content.trim() && message.content.trim() !== ' ' && (
                <span>{message.content}</span>
              )}
              {message.isStreaming && (
                <span className="inline-block w-2 h-4 ml-1 bg-current animate-pulse" />
              )}
            </>
          ) : (
            renderAiContent()
          )}
        </div>

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
