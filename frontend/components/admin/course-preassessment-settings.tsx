'use client';

import { useState, useEffect, useRef, useCallback } from 'react';
import { useTranslations } from 'next-intl';
import { useRouter } from 'next/navigation';
import { useLocale } from 'next-intl';
import {
  ChevronDown,
  ChevronUp,
  Sparkles,
  Loader2,
  CheckCircle2,
  AlertCircle,
  RefreshCw,
  ShieldCheck,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { authClient, AuthError } from '@/lib/auth';

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

interface PreassessmentQuestion {
  id: string;
  question_text: string;
  options: string[];
  correct_index: number;
  domain: string;
  difficulty: 'easy' | 'medium' | 'hard';
  explanation?: string;
}

interface PreassessmentStatus {
  enabled: boolean;
  mandatory: boolean;
  status: 'not_generated' | 'generating' | 'ready' | 'validated';
  question_count?: number;
  task_id?: string | null;
  questions?: PreassessmentQuestion[];
}

interface CoursePreassessmentSettingsProps {
  courseId: string;
  ragIndexed: boolean;
}

async function getToken(router: ReturnType<typeof useRouter>, locale: string): Promise<string | null> {
  try {
    return await authClient.getValidToken();
  } catch (err) {
    if (err instanceof AuthError && err.status === 401) {
      router.push(`/${locale}/login`);
    }
    return null;
  }
}

export function CoursePreassessmentSettings({
  courseId,
  ragIndexed,
}: CoursePreassessmentSettingsProps) {
  const t = useTranslations('AdminCourses');
  const router = useRouter();
  const locale = useLocale();

  const [expanded, setExpanded] = useState(false);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [previewOpen, setPreviewOpen] = useState(false);

  const [status, setStatus] = useState<PreassessmentStatus>({
    enabled: false,
    mandatory: false,
    status: 'not_generated',
  });

  const pollRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const fetchStatus = useCallback(async () => {
    const token = await getToken(router, locale);
    if (!token) return;
    try {
      const res = await fetch(
        `${API_BASE}/api/v1/admin/courses/${courseId}/preassessment-status`,
        { headers: { Authorization: `Bearer ${token}` } }
      );
      if (!res.ok) return;
      const data = (await res.json()) as PreassessmentStatus;
      setStatus(data);
      return data;
    } catch {
      // silently ignore fetch errors for status polling
    }
  }, [courseId, router, locale]);

  useEffect(() => {
    if (!expanded) return;
    setLoading(true);
    fetchStatus().finally(() => setLoading(false));
  }, [expanded, fetchStatus]);

  useEffect(() => {
    if (status.status !== 'generating') {
      if (pollRef.current) clearTimeout(pollRef.current);
      return;
    }

    const poll = async () => {
      const data = await fetchStatus();
      if (data?.status === 'generating') {
        pollRef.current = setTimeout(poll, 3000);
      }
    };

    pollRef.current = setTimeout(poll, 3000);
    return () => {
      if (pollRef.current) clearTimeout(pollRef.current);
    };
  }, [status.status, fetchStatus]);

  const updateSettings = async (patch: Partial<Pick<PreassessmentStatus, 'enabled' | 'mandatory'>>) => {
    setSaving(true);
    setError(null);
    const token = await getToken(router, locale);
    if (!token) { setSaving(false); return; }
    try {
      const res = await fetch(
        `${API_BASE}/api/v1/admin/courses/${courseId}/preassessment-settings`,
        {
          method: 'PATCH',
          headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
          body: JSON.stringify(patch),
        }
      );
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setStatus((prev) => ({ ...prev, ...patch }));
    } catch {
      setError(t('preassessment.saveError'));
    } finally {
      setSaving(false);
    }
  };

  const handleGenerate = async () => {
    setError(null);
    const token = await getToken(router, locale);
    if (!token) return;
    try {
      const res = await fetch(
        `${API_BASE}/api/v1/admin/courses/${courseId}/generate-preassessment`,
        {
          method: 'POST',
          headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
        }
      );
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = (await res.json()) as { task_id?: string };
      setStatus((prev) => ({
        ...prev,
        status: 'generating',
        task_id: data.task_id ?? null,
        questions: undefined,
      }));
    } catch {
      setError(t('preassessment.generateError'));
    }
  };

  const handleValidate = async () => {
    setSaving(true);
    setError(null);
    const token = await getToken(router, locale);
    if (!token) { setSaving(false); return; }
    try {
      const res = await fetch(
        `${API_BASE}/api/v1/admin/courses/${courseId}/validate-preassessment`,
        {
          method: 'POST',
          headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
        }
      );
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setStatus((prev) => ({ ...prev, status: 'validated' }));
    } catch {
      setError(t('preassessment.validateError'));
    } finally {
      setSaving(false);
    }
  };

  const statusLabel = () => {
    switch (status.status) {
      case 'not_generated':
        return t('preassessment.statusNotGenerated');
      case 'generating':
        return t('preassessment.statusGenerating');
      case 'ready':
        return t('preassessment.statusReady', { count: status.question_count ?? 0 });
      case 'validated':
        return t('preassessment.statusValidated');
    }
  };

  const statusColor = () => {
    switch (status.status) {
      case 'not_generated':
        return 'text-muted-foreground';
      case 'generating':
        return 'text-amber-600';
      case 'ready':
        return 'text-teal-700';
      case 'validated':
        return 'text-green-700';
    }
  };

  const difficultyColor = (difficulty: string) => {
    switch (difficulty) {
      case 'easy': return 'bg-green-100 text-green-800 border-green-200';
      case 'medium': return 'bg-amber-100 text-amber-800 border-amber-200';
      case 'hard': return 'bg-red-100 text-red-800 border-red-200';
      default: return 'bg-stone-100 text-stone-700 border-stone-200';
    }
  };

  return (
    <div className="border-t mt-3 pt-3">
      <button
        className="flex w-full items-center justify-between gap-2 text-sm font-medium text-muted-foreground hover:text-foreground transition-colors min-h-[44px]"
        onClick={() => setExpanded((v) => !v)}
        aria-expanded={expanded}
        aria-label={t('preassessment.sectionLabel')}
      >
        <span className="flex items-center gap-1.5">
          <ShieldCheck className="h-4 w-4 shrink-0" aria-hidden="true" />
          {t('preassessment.sectionTitle')}
        </span>
        {expanded ? (
          <ChevronUp className="h-4 w-4 shrink-0" aria-hidden="true" />
        ) : (
          <ChevronDown className="h-4 w-4 shrink-0" aria-hidden="true" />
        )}
      </button>

      {expanded && (
        <div className="mt-3 space-y-4">
          {loading ? (
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
              {t('preassessment.loading')}
            </div>
          ) : (
            <>
              <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:gap-6">
                <label className="flex items-center gap-2 cursor-pointer select-none min-h-[44px]">
                  <div
                    role="switch"
                    aria-checked={status.enabled}
                    tabIndex={0}
                    className={`relative inline-flex h-5 w-9 shrink-0 items-center rounded-full border-2 border-transparent transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background cursor-pointer ${
                      status.enabled ? 'bg-teal-600' : 'bg-input'
                    } ${saving ? 'opacity-50 pointer-events-none' : ''}`}
                    onClick={() => !saving && updateSettings({ enabled: !status.enabled })}
                    onKeyDown={(e) => {
                      if ((e.key === 'Enter' || e.key === ' ') && !saving) {
                        e.preventDefault();
                        updateSettings({ enabled: !status.enabled });
                      }
                    }}
                  >
                    <span
                      className={`pointer-events-none block h-4 w-4 rounded-full bg-background shadow-lg ring-0 transition-transform ${
                        status.enabled ? 'translate-x-4' : 'translate-x-0'
                      }`}
                    />
                  </div>
                  <span className="text-sm">{t('preassessment.enableToggle')}</span>
                </label>

                {status.enabled && (
                  <label className="flex items-center gap-2 cursor-pointer select-none min-h-[44px]">
                    <div
                      role="switch"
                      aria-checked={status.mandatory}
                      tabIndex={0}
                      className={`relative inline-flex h-5 w-9 shrink-0 items-center rounded-full border-2 border-transparent transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background cursor-pointer ${
                        status.mandatory ? 'bg-teal-600' : 'bg-input'
                      } ${saving ? 'opacity-50 pointer-events-none' : ''}`}
                      onClick={() => !saving && updateSettings({ mandatory: !status.mandatory })}
                      onKeyDown={(e) => {
                        if ((e.key === 'Enter' || e.key === ' ') && !saving) {
                          e.preventDefault();
                          updateSettings({ mandatory: !status.mandatory });
                        }
                      }}
                    >
                      <span
                        className={`pointer-events-none block h-4 w-4 rounded-full bg-background shadow-lg ring-0 transition-transform ${
                          status.mandatory ? 'translate-x-4' : 'translate-x-0'
                        }`}
                      />
                    </div>
                    <span className="text-sm">{t('preassessment.mandatoryToggle')}</span>
                  </label>
                )}
              </div>

              <div className="flex flex-wrap items-center gap-3">
                <span className={`flex items-center gap-1.5 text-sm font-medium ${statusColor()}`}>
                  {status.status === 'generating' && (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
                  )}
                  {status.status === 'validated' && (
                    <CheckCircle2 className="h-3.5 w-3.5" aria-hidden="true" />
                  )}
                  {statusLabel()}
                </span>
              </div>

              <div className="flex flex-wrap gap-2">
                <Button
                  size="sm"
                  variant="outline"
                  className="gap-1.5 min-h-11"
                  onClick={handleGenerate}
                  disabled={!ragIndexed || status.status === 'generating'}
                  title={!ragIndexed ? t('preassessment.ragNotIndexedTooltip') : undefined}
                  aria-label={t('preassessment.generateButton')}
                >
                  {status.status === 'generating' ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
                  ) : status.status === 'not_generated' ? (
                    <Sparkles className="h-3.5 w-3.5" aria-hidden="true" />
                  ) : (
                    <RefreshCw className="h-3.5 w-3.5" aria-hidden="true" />
                  )}
                  {status.status === 'not_generated'
                    ? t('preassessment.generateButton')
                    : t('preassessment.regenerateButton')}
                </Button>

                {(status.status === 'ready' || status.status === 'validated') && (
                  <>
                    <Button
                      size="sm"
                      variant="ghost"
                      className="gap-1.5 min-h-11"
                      onClick={() => setPreviewOpen((v) => !v)}
                      aria-expanded={previewOpen}
                    >
                      {previewOpen
                        ? t('preassessment.hidePreview')
                        : t('preassessment.showPreview')}
                    </Button>

                    {status.status === 'ready' && (
                      <Button
                        size="sm"
                        className="gap-1.5 min-h-11 bg-teal-600 hover:bg-teal-700"
                        onClick={handleValidate}
                        disabled={saving}
                      >
                        {saving ? (
                          <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
                        ) : (
                          <CheckCircle2 className="h-3.5 w-3.5" aria-hidden="true" />
                        )}
                        {t('preassessment.validateButton')}
                      </Button>
                    )}
                  </>
                )}
              </div>

              {error && (
                <div className="flex items-center gap-2 text-sm text-destructive" role="alert">
                  <AlertCircle className="h-4 w-4 shrink-0" aria-hidden="true" />
                  {error}
                </div>
              )}

              {previewOpen && status.questions && status.questions.length > 0 && (
                <div className="space-y-3 rounded-lg border bg-muted/30 p-4">
                  <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
                    {t('preassessment.previewTitle', { count: status.questions.length })}
                  </p>
                  <ol className="space-y-4">
                    {status.questions.map((q, idx) => (
                      <li key={q.id} className="space-y-2">
                        <div className="flex items-start gap-2 flex-wrap">
                          <span className="text-xs font-semibold text-muted-foreground shrink-0 mt-0.5">
                            {idx + 1}.
                          </span>
                          <p className="text-sm font-medium flex-1">{q.question_text}</p>
                          <div className="flex gap-1 flex-wrap shrink-0">
                            <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-medium ${difficultyColor(q.difficulty)}`}>
                              {t(`preassessment.difficulty.${q.difficulty}`)}
                            </span>
                            {q.domain && (
                              <Badge variant="outline" className="text-[10px] px-2 py-0.5">
                                {q.domain.replace(/_/g, ' ')}
                              </Badge>
                            )}
                          </div>
                        </div>
                        <ol className="ml-5 space-y-1" type="A">
                          {q.options.map((opt, oIdx) => (
                            <li
                              key={oIdx}
                              className={`text-sm rounded px-2 py-1 ${
                                oIdx === q.correct_index
                                  ? 'bg-teal-50 text-teal-800 font-medium border border-teal-200'
                                  : 'text-muted-foreground'
                              }`}
                            >
                              {String.fromCharCode(65 + oIdx)}. {opt}
                            </li>
                          ))}
                        </ol>
                      </li>
                    ))}
                  </ol>
                </div>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}
