'use client';

import { useState, useRef, useEffect, useCallback } from 'react';
import { useTranslations, useLocale } from 'next-intl';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Badge } from '@/components/ui/badge';
import { Separator } from '@/components/ui/separator';
import { Send, Save, Download, Loader2, X, Bot, User } from 'lucide-react';
import { authClient, AuthError } from '@/lib/auth';
import { useRouter } from 'next/navigation';
import type { AdminModuleCardData } from './module-card';

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  toolCalls?: { tool: string; result_summary: string }[];
}

interface ModuleDraft {
  module_number?: number;
  level: number;
  title_fr: string;
  title_en: string;
  description_fr?: string;
  description_en?: string;
  objectives_fr: string[];
  objectives_en: string[];
  key_contents_fr: string[];
  key_contents_en: string[];
  aof_context_fr?: string;
  aof_context_en?: string;
  activities: {
    quiz_topics: string[];
    flashcard_count: number;
    case_study_scenario: string;
  };
  source_references: string[];
  estimated_hours: number;
  bloom_level?: string;
}

interface SyllabusEditorProps {
  editingModule: AdminModuleCardData | null;
  onClose: () => void;
  onSaved: () => void;
}

export function SyllabusEditor({ editingModule, onClose, onSaved }: SyllabusEditorProps) {
  const t = useTranslations('AdminSyllabus');
  const locale = useLocale() as 'fr' | 'en';
  const router = useRouter();

  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [isStreaming, setIsStreaming] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [draft, setDraft] = useState<ModuleDraft | null>(null);
  const [conversationHistory, setConversationHistory] = useState<
    { role: string; content: string }[]
  >([]);

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    const welcome = editingModule
      ? `${t('welcomeEdit')} **M${String(editingModule.module_number).padStart(2, '0')} — ${locale === 'fr' ? editingModule.title_fr : editingModule.title_en}**. ${t('welcomeEditHint')}`
      : t('welcomeCreate');

    setMessages([{ id: 'welcome', role: 'assistant', content: welcome }]);
    setDraft(null);
    setConversationHistory([]);
  }, [editingModule, t, locale]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const sendMessage = useCallback(async () => {
    if (!input.trim() || isStreaming) return;

    const userMsg: ChatMessage = {
      id: Date.now().toString(),
      role: 'user',
      content: input.trim(),
    };
    setMessages((prev) => [...prev, userMsg]);

    const newHistory = [
      ...conversationHistory,
      { role: 'user', content: input.trim() },
    ];

    setInput('');
    setIsStreaming(true);

    const aiMsgId = (Date.now() + 1).toString();
    setMessages((prev) => [
      ...prev,
      { id: aiMsgId, role: 'assistant', content: '' },
    ]);

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

      const response = await fetch(`${API_BASE}/api/v1/admin/syllabus/agent`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({
          message: userMsg.content,
          module_id: editingModule?.id ?? null,
          conversation_history: conversationHistory,
        }),
      });

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }

      const reader = response.body?.getReader();
      const decoder = new TextDecoder();
      let fullContent = '';
      const toolCalls: { tool: string; result_summary: string }[] = [];

      if (reader) {
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          const text = decoder.decode(value, { stream: true });
          for (const line of text.split('\n')) {
            if (!line.startsWith('data: ')) continue;
            try {
              const chunk = JSON.parse(line.slice(6));
              if (chunk.type === 'content' && chunk.data?.text) {
                fullContent += chunk.data.text;
                setMessages((prev) =>
                  prev.map((m) =>
                    m.id === aiMsgId
                      ? { ...m, content: fullContent, toolCalls }
                      : m
                  )
                );
              } else if (chunk.type === 'tool_call' && chunk.data) {
                toolCalls.push({
                  tool: chunk.data.tool,
                  result_summary: chunk.data.result_summary,
                });
                setMessages((prev) =>
                  prev.map((m) =>
                    m.id === aiMsgId ? { ...m, toolCalls: [...toolCalls] } : m
                  )
                );
              } else if (chunk.type === 'done') {
                break;
              }
            } catch {
            }
          }
        }
      }

      setConversationHistory([
        ...newHistory,
        { role: 'assistant', content: fullContent },
      ]);

      parseDraftFromContent(fullContent);
    } catch {
      setMessages((prev) =>
        prev.map((m) =>
          m.id === aiMsgId ? { ...m, content: t('errorMessage') } : m
        )
      );
    } finally {
      setIsStreaming(false);
    }
  }, [input, isStreaming, conversationHistory, editingModule, router, t]);

  const parseDraftFromContent = (content: string) => {
    const titleFrMatch = content.match(/##\s+MODULE\s+M\d+\s+—\s+([^/\n]+)\s*\/\s*(.+)/i);
    if (!titleFrMatch) return;

    const levelMatch = content.match(/\*\*Niveau\s*:\*\*\s*(\d)/i);
    const bloomMatch = content.match(/\*\*Bloom\s*:\*\*\s*(\w+)/i);
    const durationMatch = content.match(/\*\*Durée\s*:\*\*\s*(\d+)/i);

    const objectivesFrRaw = content.match(/### Objectifs.*?\n([\s\S]*?)(?=###|$)/i)?.[1] ?? '';
    const objectivesFr = objectivesFrRaw
      .split('\n')
      .filter((l) => /^\d+\./.test(l.trim()))
      .map((l) => l.replace(/^\d+\.\s*/, '').split('/')[0].trim())
      .filter(Boolean);
    const objectivesEn = objectivesFrRaw
      .split('\n')
      .filter((l) => /^\d+\./.test(l.trim()))
      .map((l) => {
        const parts = l.replace(/^\d+\.\s*/, '').split('/');
        return (parts[1] ?? parts[0]).trim();
      })
      .filter(Boolean);

    const contentsFrRaw = content.match(/### Contenus.*?\n([\s\S]*?)(?=###|$)/i)?.[1] ?? '';
    const keyContentsFr = contentsFrRaw
      .split('\n')
      .filter((l) => l.trim().startsWith('-'))
      .map((l) => l.replace(/^-\s*/, '').split('/')[0].trim())
      .filter(Boolean);
    const keyContentsEn = contentsFrRaw
      .split('\n')
      .filter((l) => l.trim().startsWith('-'))
      .map((l) => {
        const parts = l.replace(/^-\s*/, '').split('/');
        return (parts[1] ?? parts[0]).trim();
      })
      .filter(Boolean);

    const aofFrMatch = content.match(/\*\*FR\s*:\*\*\s*([^\n*]+)/);
    const aofEnMatch = content.match(/\*\*EN\s*:\*\*\s*([^\n*]+)/);

    const caseStudyMatch = content.match(/Étude de cas\s*:\s*([^\n]+)/i);

    setDraft({
      level: levelMatch ? parseInt(levelMatch[1]) : 1,
      title_fr: titleFrMatch[1].trim(),
      title_en: titleFrMatch[2].trim(),
      objectives_fr: objectivesFr,
      objectives_en: objectivesEn,
      key_contents_fr: keyContentsFr,
      key_contents_en: keyContentsEn,
      aof_context_fr: aofFrMatch?.[1]?.trim() ?? '',
      aof_context_en: aofEnMatch?.[1]?.trim() ?? '',
      activities: {
        quiz_topics: [],
        flashcard_count: 20,
        case_study_scenario: caseStudyMatch?.[1]?.trim() ?? '',
      },
      source_references: [],
      estimated_hours: durationMatch ? parseInt(durationMatch[1]) : 20,
      bloom_level: bloomMatch?.[1]?.toLowerCase() ?? undefined,
    });
  };

  const handleSave = async () => {
    if (!draft || isSaving) return;
    setIsSaving(true);
    try {
      let token: string;
      try {
        token = await authClient.getValidToken();
      } catch {
        router.push('/login');
        return;
      }

      const url = editingModule
        ? `${API_BASE}/api/v1/admin/syllabus/${editingModule.id}`
        : `${API_BASE}/api/v1/admin/syllabus/agent`;

      if (editingModule) {
        const res = await fetch(url, {
          method: 'PUT',
          headers: {
            'Content-Type': 'application/json',
            Authorization: `Bearer ${token}`,
          },
          body: JSON.stringify({ draft }),
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
      } else {
        const res = await fetch(`${API_BASE}/api/v1/admin/syllabus/agent`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            Authorization: `Bearer ${token}`,
          },
          body: JSON.stringify({
            message: `Please save this module draft: ${JSON.stringify(draft)}`,
            conversation_history: conversationHistory,
          }),
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const reader = res.body?.getReader();
        if (reader) {
          while (true) {
            const { done } = await reader.read();
            if (done) break;
          }
        }
      }

      onSaved();
    } catch {
      setMessages((prev) => [
        ...prev,
        { id: Date.now().toString(), role: 'assistant', content: t('saveError') },
      ]);
    } finally {
      setIsSaving(false);
    }
  };

  const handleExport = async () => {
    if (!editingModule) return;
    try {
      const token = await authClient.getValidToken();
      const res = await fetch(
        `${API_BASE}/api/v1/admin/syllabus/${editingModule.id}/export`,
        { headers: { Authorization: `Bearer ${token}` } }
      );
      if (!res.ok) return;
      const data = await res.json();
      const blob = new Blob([data.markdown], { type: 'text/markdown' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `module_M${String(data.module_number).padStart(2, '0')}.md`;
      a.click();
      URL.revokeObjectURL(url);
    } catch {
    }
  };

  return (
    <div className="fixed inset-0 z-50 bg-background flex flex-col md:flex-row">
      <div className="flex items-center justify-between p-4 border-b md:hidden">
        <h2 className="font-semibold">
          {editingModule ? t('editModule') : t('createModule')}
        </h2>
        <Button variant="ghost" size="icon" onClick={onClose}>
          <X className="h-4 w-4" />
        </Button>
      </div>

      <div className="flex flex-col flex-1 min-h-0 md:w-1/2 md:border-r">
        <div className="hidden md:flex items-center justify-between p-4 border-b">
          <h2 className="font-semibold">
            {editingModule ? t('editModule') : t('createModule')}
          </h2>
          <Button variant="ghost" size="icon" onClick={onClose}>
            <X className="h-4 w-4" />
          </Button>
        </div>

        <ScrollArea className="flex-1 p-4">
          <div className="space-y-4">
            {messages.map((msg) => (
              <div
                key={msg.id}
                className={`flex gap-3 ${msg.role === 'user' ? 'flex-row-reverse' : ''}`}
              >
                <div
                  className={`h-8 w-8 rounded-full flex items-center justify-center shrink-0 ${
                    msg.role === 'user' ? 'bg-primary text-primary-foreground' : 'bg-muted'
                  }`}
                >
                  {msg.role === 'user' ? (
                    <User className="h-4 w-4" />
                  ) : (
                    <Bot className="h-4 w-4" />
                  )}
                </div>
                <div
                  className={`rounded-lg p-3 max-w-[85%] text-sm whitespace-pre-wrap ${
                    msg.role === 'user'
                      ? 'bg-primary text-primary-foreground'
                      : 'bg-muted'
                  }`}
                >
                  {msg.content || (isStreaming && msg.role === 'assistant' && (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ))}
                  {msg.toolCalls && msg.toolCalls.length > 0 && (
                    <div className="mt-2 space-y-1">
                      {msg.toolCalls.map((tc, i) => (
                        <div
                          key={i}
                          className="text-xs opacity-70 flex items-center gap-1"
                        >
                          <span>🔧</span>
                          <span className="font-mono">{tc.tool}</span>
                          <span>→</span>
                          <span>{tc.result_summary}</span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            ))}
            <div ref={messagesEndRef} />
          </div>
        </ScrollArea>

        <div className="p-4 border-t flex gap-2">
          <Textarea
            ref={inputRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder={t('chatPlaceholder')}
            className="min-h-[44px] max-h-32 resize-none"
            rows={2}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                sendMessage();
              }
            }}
            disabled={isStreaming}
          />
          <Button
            size="icon"
            onClick={sendMessage}
            disabled={isStreaming || !input.trim()}
            className="h-11 w-11 shrink-0"
            aria-label={t('send')}
          >
            {isStreaming ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Send className="h-4 w-4" />
            )}
          </Button>
        </div>
      </div>

      <div className="flex flex-col flex-1 min-h-0 md:w-1/2">
        <div className="flex items-center justify-between p-4 border-b">
          <h3 className="font-semibold text-sm">{t('previewTitle')}</h3>
          <div className="flex gap-2">
            {editingModule && (
              <Button
                size="sm"
                variant="outline"
                onClick={handleExport}
                className="gap-1"
              >
                <Download className="h-3 w-3" />
                {t('exportMarkdown')}
              </Button>
            )}
            <Button
              size="sm"
              onClick={handleSave}
              disabled={!draft || isSaving}
              className="gap-1"
            >
              {isSaving ? (
                <Loader2 className="h-3 w-3 animate-spin" />
              ) : (
                <Save className="h-3 w-3" />
              )}
              {t('save')}
            </Button>
          </div>
        </div>

        <ScrollArea className="flex-1 p-4">
          {draft ? (
            <ModuleDraftPreview
              draft={draft}
              onChange={setDraft}
              t={t}
            />
          ) : (
            <div className="flex flex-col items-center justify-center h-full text-muted-foreground text-sm text-center p-8">
              <Bot className="h-12 w-12 mb-3 opacity-30" />
              <p>{t('previewEmpty')}</p>
            </div>
          )}
        </ScrollArea>
      </div>
    </div>
  );
}

interface ModuleDraftPreviewProps {
  draft: ModuleDraft;
  onChange: (draft: ModuleDraft) => void;
  t: ReturnType<typeof useTranslations<'AdminSyllabus'>>;
}

function ModuleDraftPreview({ draft, onChange, t }: ModuleDraftPreviewProps) {
  const update = (key: keyof ModuleDraft, value: unknown) =>
    onChange({ ...draft, [key]: value });

  return (
    <div className="space-y-5 text-sm">
      <div className="grid grid-cols-2 gap-3">
        <div>
          <Label className="text-xs">{t('titleFr')}</Label>
          <Input
            value={draft.title_fr}
            onChange={(e) => update('title_fr', e.target.value)}
            className="mt-1 h-8 text-sm"
          />
        </div>
        <div>
          <Label className="text-xs">{t('titleEn')}</Label>
          <Input
            value={draft.title_en}
            onChange={(e) => update('title_en', e.target.value)}
            className="mt-1 h-8 text-sm"
          />
        </div>
      </div>

      <div className="grid grid-cols-3 gap-3">
        <div>
          <Label className="text-xs">{t('level')}</Label>
          <Input
            type="number"
            min={1}
            max={4}
            value={draft.level}
            onChange={(e) => update('level', parseInt(e.target.value) || 1)}
            className="mt-1 h-8 text-sm"
          />
        </div>
        <div>
          <Label className="text-xs">{t('estimatedHours')}</Label>
          <Input
            type="number"
            min={1}
            value={draft.estimated_hours}
            onChange={(e) => update('estimated_hours', parseInt(e.target.value) || 20)}
            className="mt-1 h-8 text-sm"
          />
        </div>
        <div>
          <Label className="text-xs">{t('bloomLevel')}</Label>
          <Input
            value={draft.bloom_level ?? ''}
            onChange={(e) => update('bloom_level', e.target.value)}
            className="mt-1 h-8 text-sm"
          />
        </div>
      </div>

      <Separator />

      <div>
        <Label className="text-xs">{t('descriptionFr')}</Label>
        <Textarea
          value={draft.description_fr ?? ''}
          onChange={(e) => update('description_fr', e.target.value)}
          className="mt-1 min-h-[60px] text-sm resize-none"
          rows={2}
        />
      </div>
      <div>
        <Label className="text-xs">{t('descriptionEn')}</Label>
        <Textarea
          value={draft.description_en ?? ''}
          onChange={(e) => update('description_en', e.target.value)}
          className="mt-1 min-h-[60px] text-sm resize-none"
          rows={2}
        />
      </div>

      <Separator />

      <div>
        <Label className="text-xs">{t('objectivesFr')}</Label>
        <div className="mt-1 space-y-1">
          {draft.objectives_fr.map((obj, i) => (
            <Input
              key={i}
              value={obj}
              onChange={(e) => {
                const updated = [...draft.objectives_fr];
                updated[i] = e.target.value;
                update('objectives_fr', updated);
              }}
              className="h-8 text-sm"
            />
          ))}
        </div>
      </div>
      <div>
        <Label className="text-xs">{t('objectivesEn')}</Label>
        <div className="mt-1 space-y-1">
          {draft.objectives_en.map((obj, i) => (
            <Input
              key={i}
              value={obj}
              onChange={(e) => {
                const updated = [...draft.objectives_en];
                updated[i] = e.target.value;
                update('objectives_en', updated);
              }}
              className="h-8 text-sm"
            />
          ))}
        </div>
      </div>

      <Separator />

      <div>
        <Label className="text-xs">{t('aofContextFr')}</Label>
        <Textarea
          value={draft.aof_context_fr ?? ''}
          onChange={(e) => update('aof_context_fr', e.target.value)}
          className="mt-1 min-h-[60px] text-sm resize-none"
          rows={2}
        />
      </div>
      <div>
        <Label className="text-xs">{t('aofContextEn')}</Label>
        <Textarea
          value={draft.aof_context_en ?? ''}
          onChange={(e) => update('aof_context_en', e.target.value)}
          className="mt-1 min-h-[60px] text-sm resize-none"
          rows={2}
        />
      </div>

      <Separator />

      <div>
        <Label className="text-xs">{t('caseStudy')}</Label>
        <Input
          value={draft.activities.case_study_scenario}
          onChange={(e) =>
            update('activities', {
              ...draft.activities,
              case_study_scenario: e.target.value,
            })
          }
          className="mt-1 h-8 text-sm"
        />
      </div>
      <div>
        <Label className="text-xs">{t('flashcardCount')}</Label>
        <Input
          type="number"
          min={10}
          max={50}
          value={draft.activities.flashcard_count}
          onChange={(e) =>
            update('activities', {
              ...draft.activities,
              flashcard_count: parseInt(e.target.value) || 20,
            })
          }
          className="mt-1 h-8 text-sm"
        />
      </div>

      {draft.source_references.length > 0 && (
        <>
          <Separator />
          <div>
            <Label className="text-xs">{t('sources')}</Label>
            <div className="mt-1 flex flex-wrap gap-1">
              {draft.source_references.map((ref, i) => (
                <Badge key={i} variant="secondary" className="text-xs">
                  {ref}
                </Badge>
              ))}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
