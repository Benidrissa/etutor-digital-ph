'use client';

import { useState, useEffect, useRef, useCallback } from 'react';
import { useTranslations } from 'next-intl';
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
import { authClient } from '@/lib/auth';

interface PreassessmentQuestion {
  id: string;
  question: string;
  options: Array<{ id: string; text: string }>;
  domain: string;
  level: number;
  correct_index?: number;
  difficulty?: 'easy' | 'medium' | 'hard';
}

interface BackendPreassessmentEntry {
  id: string;
  language: string;
  question_count: number;
  generated_by: string;
  created_at: string;
  validated?: boolean;
  questions?: PreassessmentQuestion[];
}

interface BackendStatusResponse {
  course_id: string;
  preassessment_enabled: boolean;
  preassessments: BackendPreassessmentEntry[];
  task?: {
    id: string;
    state: string;
    step?: string;
    progress?: number;
    question_count?: number;
    preassessment_id?: string;
  };
}

type GenerationStatus = 'not_generated' | 'generating' | 'ready' | 'validated';

interface LocalState {
  enabled: boolean;
  mandatory: boolean;
  status: GenerationStatus;
  questionCount: number;
  taskId: string | null;
  questions: PreassessmentQuestion[];
  validated: boolean;
}

interface CoursePreassessmentSettingsProps {
  courseId: string;
  ragIndexed: boolean;
  preassessmentEnabled: boolean;
  preassessmentMandatory: boolean;
  courseTitleFr: string;
  courseTitleEn: string;
}

function deriveStatus(
  response: BackendStatusResponse,
  localTaskId: string | null,
  localGenerating: boolean,
): GenerationStatus {
  if (localGenerating) return 'generating';
  if (response.task && ['PENDING', 'STARTED', 'GENERATING'].includes(response.task.state)) {
    return 'generating';
  }
  if (response.preassessments.length === 0) return 'not_generated';
  const latest = response.preassessments[0];
  if (latest.validated) return 'validated';
  if (latest.question_count > 0) return 'ready';
  return 'not_generated';
}

export function CoursePreassessmentSettings({
  courseId,
  ragIndexed,
  preassessmentEnabled,
  preassessmentMandatory,
  courseTitleFr,
  courseTitleEn,
}: CoursePreassessmentSettingsProps) {
  const t = useTranslations('AdminCourses');

  const [expanded, setExpanded] = useState(false);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [previewOpen, setPreviewOpen] = useState(false);

  const [local, setLocal] = useState<LocalState>({
    enabled: preassessmentEnabled,
    mandatory: preassessmentMandatory,
    status: 'not_generated',
    questionCount: 0,
    taskId: null,
    questions: [],
    validated: false,
  });

  const pollRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const generatingRef = useRef(false);

  const fetchStatus = useCallback(
    async (taskId?: string | null): Promise<BackendStatusResponse | null> => {
      try {
        const params = taskId ? `?task_id=${encodeURIComponent(taskId)}` : '';
        const data = await authClient.authenticatedFetch<BackendStatusResponse>(
          `/api/v1/admin/courses/${courseId}/preassessment-status${params}`,
        );
        return data;
      } catch {
        return null;
      }
    },
    [courseId],
  );

  const applyResponse = useCallback(
    (data: BackendStatusResponse, currentTaskId: string | null, isGenerating: boolean) => {
      const status = deriveStatus(data, currentTaskId, isGenerating);
      const latest = data.preassessments[0] ?? null;
      setLocal((prev) => ({
        ...prev,
        enabled: data.preassessment_enabled,
        status,
        questionCount: latest?.question_count ?? 0,
        validated: latest?.validated ?? false,
        questions: (latest?.questions as PreassessmentQuestion[] | undefined) ?? [],
      }));
    },
    [],
  );

  useEffect(() => {
    if (!expanded) return;
    setLoading(true);
    fetchStatus(null).then((data) => {
      if (data) applyResponse(data, null, false);
      setLoading(false);
    });
  }, [expanded, fetchStatus, applyResponse]);

  useEffect(() => {
    if (local.status !== 'generating') {
      if (pollRef.current) clearTimeout(pollRef.current);
      generatingRef.current = false;
      return;
    }

    generatingRef.current = true;

    const poll = async () => {
      const data = await fetchStatus(local.taskId);
      if (!data) {
        if (generatingRef.current) {
          pollRef.current = setTimeout(poll, 3000);
        }
        return;
      }
      const taskDone =
        !data.task ||
        !['PENDING', 'STARTED', 'GENERATING'].includes(data.task.state);
      const hasResults = data.preassessments.length > 0;

      if (taskDone && (hasResults || data.task?.state === 'FAILURE')) {
        applyResponse(data, local.taskId, false);
        generatingRef.current = false;
        setLocal((prev) => ({ ...prev, taskId: null }));
      } else {
        applyResponse(data, local.taskId, true);
        if (generatingRef.current) {
          pollRef.current = setTimeout(poll, 3000);
        }
      }
    };

    pollRef.current = setTimeout(poll, 3000);
    return () => {
      if (pollRef.current) clearTimeout(pollRef.current);
    };
  }, [local.status, local.taskId, fetchStatus, applyResponse]);

  const updateSettings = async (patch: { enabled?: boolean; mandatory?: boolean }) => {
    setSaving(true);
    setError(null);
    try {
      const body: Record<string, unknown> = {
        title_fr: courseTitleFr,
        title_en: courseTitleEn,
      };
      if (patch.enabled !== undefined) body.preassessment_enabled = patch.enabled;
      if (patch.mandatory !== undefined) body.preassessment_mandatory = patch.mandatory;

      await authClient.authenticatedFetch(
        `/api/v1/admin/courses/${courseId}`,
        {
          method: 'PATCH',
          body: JSON.stringify(body),
        },
      );
      setLocal((prev) => ({
        ...prev,
        ...(patch.enabled !== undefined ? { enabled: patch.enabled! } : {}),
        ...(patch.mandatory !== undefined ? { mandatory: patch.mandatory! } : {}),
      }));
    } catch {
      setError(t('preassessment.saveError'));
    } finally {
      setSaving(false);
    }
  };

  const handleGenerate = async () => {
    setError(null);
    try {
      const data = await authClient.authenticatedFetch<{ task_id?: string; status?: string }>(
        `/api/v1/admin/courses/${courseId}/generate-preassessment`,
        {
          method: 'POST',
          body: JSON.stringify({ language: 'fr' }),
        },
      );
      setLocal((prev) => ({
        ...prev,
        status: 'generating',
        taskId: data.task_id ?? null,
        questions: [],
      }));
    } catch {
      setError(t('preassessment.generateError'));
    }
  };

  const handleValidate = async () => {
    setSaving(true);
    setError(null);
    try {
      await authClient.authenticatedFetch(
        `/api/v1/admin/courses/${courseId}/validate-preassessment`,
        { method: 'POST' },
      );
      setLocal((prev) => ({ ...prev, status: 'validated', validated: true }));
    } catch {
      setError(t('preassessment.validateError'));
    } finally {
      setSaving(false);
    }
  };

  const statusLabel = () => {
    switch (local.status) {
      case 'not_generated':
        return t('preassessment.statusNotGenerated');
      case 'generating':
        return t('preassessment.statusGenerating');
      case 'ready':
        return t('preassessment.statusReady', { count: local.questionCount });
      case 'validated':
        return t('preassessment.statusValidated');
    }
  };

  const statusColor = () => {
    switch (local.status) {
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

  const difficultyColor = (difficulty?: string) => {
    switch (difficulty) {
      case 'easy':
        return 'bg-green-100 text-green-800 border-green-200';
      case 'medium':
        return 'bg-amber-100 text-amber-800 border-amber-200';
      case 'hard':
        return 'bg-red-100 text-red-800 border-red-200';
      default:
        return 'bg-stone-100 text-stone-700 border-stone-200';
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
                    aria-checked={local.enabled}
                    tabIndex={0}
                    className={`relative inline-flex h-5 w-9 shrink-0 items-center rounded-full border-2 border-transparent transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background cursor-pointer ${
                      local.enabled ? 'bg-teal-600' : 'bg-input'
                    } ${saving ? 'opacity-50 pointer-events-none' : ''}`}
                    onClick={() => !saving && updateSettings({ enabled: !local.enabled })}
                    onKeyDown={(e) => {
                      if ((e.key === 'Enter' || e.key === ' ') && !saving) {
                        e.preventDefault();
                        updateSettings({ enabled: !local.enabled });
                      }
                    }}
                  >
                    <span
                      className={`pointer-events-none block h-4 w-4 rounded-full bg-background shadow-lg ring-0 transition-transform ${
                        local.enabled ? 'translate-x-4' : 'translate-x-0'
                      }`}
                    />
                  </div>
                  <span className="text-sm">{t('preassessment.enableToggle')}</span>
                </label>

                {local.enabled && (
                  <label className="flex items-center gap-2 cursor-pointer select-none min-h-[44px]">
                    <div
                      role="switch"
                      aria-checked={local.mandatory}
                      tabIndex={0}
                      className={`relative inline-flex h-5 w-9 shrink-0 items-center rounded-full border-2 border-transparent transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background cursor-pointer ${
                        local.mandatory ? 'bg-teal-600' : 'bg-input'
                      } ${saving ? 'opacity-50 pointer-events-none' : ''}`}
                      onClick={() => !saving && updateSettings({ mandatory: !local.mandatory })}
                      onKeyDown={(e) => {
                        if ((e.key === 'Enter' || e.key === ' ') && !saving) {
                          e.preventDefault();
                          updateSettings({ mandatory: !local.mandatory });
                        }
                      }}
                    >
                      <span
                        className={`pointer-events-none block h-4 w-4 rounded-full bg-background shadow-lg ring-0 transition-transform ${
                          local.mandatory ? 'translate-x-4' : 'translate-x-0'
                        }`}
                      />
                    </div>
                    <span className="text-sm">{t('preassessment.mandatoryToggle')}</span>
                  </label>
                )}
              </div>

              <div className="flex flex-wrap items-center gap-3">
                <span className={`flex items-center gap-1.5 text-sm font-medium ${statusColor()}`}>
                  {local.status === 'generating' && (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
                  )}
                  {local.status === 'validated' && (
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
                  disabled={!ragIndexed || local.status === 'generating'}
                  title={!ragIndexed ? t('preassessment.ragNotIndexedTooltip') : undefined}
                  aria-label={t('preassessment.generateButton')}
                >
                  {local.status === 'generating' ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
                  ) : local.status === 'not_generated' ? (
                    <Sparkles className="h-3.5 w-3.5" aria-hidden="true" />
                  ) : (
                    <RefreshCw className="h-3.5 w-3.5" aria-hidden="true" />
                  )}
                  {local.status === 'not_generated'
                    ? t('preassessment.generateButton')
                    : t('preassessment.regenerateButton')}
                </Button>

                {(local.status === 'ready' || local.status === 'validated') && (
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

                    {local.status === 'ready' && (
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

              {previewOpen && local.questions.length > 0 && (
                <div className="space-y-3 rounded-lg border bg-muted/30 p-4">
                  <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
                    {t('preassessment.previewTitle', { count: local.questions.length })}
                  </p>
                  <ol className="space-y-4">
                    {local.questions.map((q, idx) => (
                      <li key={q.id} className="space-y-2">
                        <div className="flex items-start gap-2 flex-wrap">
                          <span className="text-xs font-semibold text-muted-foreground shrink-0 mt-0.5">
                            {idx + 1}.
                          </span>
                          <p className="text-sm font-medium flex-1">{q.question}</p>
                          <div className="flex gap-1 flex-wrap shrink-0">
                            {q.difficulty && (
                              <span
                                className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-medium ${difficultyColor(q.difficulty)}`}
                              >
                                {t(`preassessment.difficulty.${q.difficulty}`)}
                              </span>
                            )}
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
                              key={opt.id || oIdx}
                              className={`text-sm rounded px-2 py-1 ${
                                oIdx === q.correct_index
                                  ? 'bg-teal-50 text-teal-800 font-medium border border-teal-200'
                                  : 'text-muted-foreground'
                              }`}
                            >
                              {String.fromCharCode(65 + oIdx)}. {opt.text}
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
