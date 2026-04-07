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

type Language = 'fr' | 'en';

interface LangTaskState {
  taskId: string | null;
  status: GenerationStatus;
  questionCount: number;
  validated: boolean;
  questions: PreassessmentQuestion[];
}

interface LocalState {
  enabled: boolean;
  mandatory: boolean;
  fr: LangTaskState;
  en: LangTaskState;
}

const defaultLangState = (): LangTaskState => ({
  taskId: null,
  status: 'not_generated',
  questionCount: 0,
  validated: false,
  questions: [],
});

interface CoursePreassessmentSettingsProps {
  courseId: string;
  ragIndexed: boolean;
  preassessmentEnabled: boolean;
  preassessmentMandatory: boolean;
  courseTitleFr: string;
  courseTitleEn: string;
}

function deriveLangStatus(
  entry: BackendPreassessmentEntry | null,
  taskId: string | null,
  isGenerating: boolean,
  taskState?: string,
): GenerationStatus {
  if (isGenerating) return 'generating';
  if (taskState && ['PENDING', 'STARTED', 'GENERATING'].includes(taskState)) return 'generating';
  if (!entry) return 'not_generated';
  if (entry.validated) return 'validated';
  if (entry.question_count > 0) return 'ready';
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
  const [previewLang, setPreviewLang] = useState<Language | null>(null);

  const [local, setLocal] = useState<LocalState>({
    enabled: preassessmentEnabled,
    mandatory: preassessmentMandatory,
    fr: defaultLangState(),
    en: defaultLangState(),
  });

  const pollRef = useRef<Record<Language, ReturnType<typeof setTimeout> | null>>({
    fr: null,
    en: null,
  });
  const generatingRef = useRef<Record<Language, boolean>>({ fr: false, en: false });

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
    (
      data: BackendStatusResponse,
      taskIds: Record<Language, string | null>,
      generatingFlags: Record<Language, boolean>,
    ) => {
      const frEntry = data.preassessments.find((p) => p.language === 'fr') ?? null;
      const enEntry = data.preassessments.find((p) => p.language === 'en') ?? null;
      const taskState = data.task?.state;

      setLocal((prev) => ({
        ...prev,
        enabled: data.preassessment_enabled,
        fr: {
          taskId: taskIds.fr,
          status: deriveLangStatus(frEntry, taskIds.fr, generatingFlags.fr, taskState),
          questionCount: frEntry?.question_count ?? 0,
          validated: frEntry?.validated ?? false,
          questions: (frEntry?.questions as PreassessmentQuestion[] | undefined) ?? [],
        },
        en: {
          taskId: taskIds.en,
          status: deriveLangStatus(enEntry, taskIds.en, generatingFlags.en, taskState),
          questionCount: enEntry?.question_count ?? 0,
          validated: enEntry?.validated ?? false,
          questions: (enEntry?.questions as PreassessmentQuestion[] | undefined) ?? [],
        },
      }));
    },
    [],
  );

  useEffect(() => {
    if (!expanded) return;
    setLoading(true);
    fetchStatus(null).then((data) => {
      if (data) applyResponse(data, { fr: null, en: null }, { fr: false, en: false });
      setLoading(false);
    });
  }, [expanded, fetchStatus, applyResponse]);

  const startPolling = useCallback(
    (lang: Language, taskId: string | null) => {
      if (pollRef.current[lang]) clearTimeout(pollRef.current[lang]!);
      generatingRef.current[lang] = true;

      const poll = async () => {
        const data = await fetchStatus(taskId);
        if (!data) {
          if (generatingRef.current[lang]) {
            pollRef.current[lang] = setTimeout(poll, 3000);
          }
          return;
        }
        const taskDone =
          !data.task || !['PENDING', 'STARTED', 'GENERATING'].includes(data.task.state);
        const entry = data.preassessments.find((p) => p.language === lang) ?? null;
        const hasResult = !!entry && entry.question_count > 0;

        if (taskDone && (hasResult || data.task?.state === 'FAILURE')) {
          generatingRef.current[lang] = false;
          setLocal((prev) => {
            const langEntry = data.preassessments.find((p) => p.language === lang) ?? null;
            const status = deriveLangStatus(langEntry, null, false, data.task?.state);
            return {
              ...prev,
              [lang]: {
                taskId: null,
                status,
                questionCount: langEntry?.question_count ?? 0,
                validated: langEntry?.validated ?? false,
                questions:
                  (langEntry?.questions as PreassessmentQuestion[] | undefined) ?? [],
              },
            };
          });
        } else {
          setLocal((prev) => ({
            ...prev,
            [lang]: {
              ...prev[lang],
              status: 'generating',
            },
          }));
          if (generatingRef.current[lang]) {
            pollRef.current[lang] = setTimeout(poll, 3000);
          }
        }
      };

      pollRef.current[lang] = setTimeout(poll, 3000);
    },
    [fetchStatus],
  );

  useEffect(() => {
    const polls = pollRef.current;
    return () => {
      if (polls.fr) clearTimeout(polls.fr);
      if (polls.en) clearTimeout(polls.en);
    };
  }, []);

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

  const generateForLang = async (lang: Language): Promise<string | null> => {
    const data = await authClient.authenticatedFetch<{ task_id?: string; status?: string }>(
      `/api/v1/admin/courses/${courseId}/generate-preassessment`,
      {
        method: 'POST',
        body: JSON.stringify({ language: lang }),
      },
    );
    return data.task_id ?? null;
  };

  const handleGenerate = async () => {
    setError(null);
    setLocal((prev) => ({
      ...prev,
      fr: { ...prev.fr, status: 'generating', questions: [] },
      en: { ...prev.en, status: 'generating', questions: [] },
    }));
    try {
      const [frTaskId, enTaskId] = await Promise.all([
        generateForLang('fr'),
        generateForLang('en'),
      ]);
      setLocal((prev) => ({
        ...prev,
        fr: { ...prev.fr, taskId: frTaskId },
        en: { ...prev.en, taskId: enTaskId },
      }));
      startPolling('fr', frTaskId);
      startPolling('en', enTaskId);
    } catch {
      setError(t('preassessment.generateError'));
      setLocal((prev) => ({
        ...prev,
        fr: { ...prev.fr, status: prev.fr.questionCount > 0 ? 'ready' : 'not_generated' },
        en: { ...prev.en, status: prev.en.questionCount > 0 ? 'ready' : 'not_generated' },
      }));
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
      setLocal((prev) => ({
        ...prev,
        fr: { ...prev.fr, status: 'validated', validated: true },
        en: { ...prev.en, status: 'validated', validated: true },
      }));
    } catch {
      setError(t('preassessment.validateError'));
    } finally {
      setSaving(false);
    }
  };

  const isGenerating = local.fr.status === 'generating' || local.en.status === 'generating';
  const bothReady =
    (local.fr.status === 'ready' || local.fr.status === 'validated') &&
    (local.en.status === 'ready' || local.en.status === 'validated');
  const anyReady = local.fr.status === 'ready' || local.en.status === 'ready';
  const neitherGenerated =
    local.fr.status === 'not_generated' && local.en.status === 'not_generated';

  const overallStatusLabel = () => {
    if (isGenerating) return t('preassessment.statusGenerating');
    if (neitherGenerated) return t('preassessment.statusNotGenerated');
    const parts: string[] = [];
    if (local.fr.status === 'validated' || local.fr.status === 'ready') {
      parts.push(
        t('preassessment.statusLangReady', { lang: 'FR', count: local.fr.questionCount }),
      );
    }
    if (local.en.status === 'validated' || local.en.status === 'ready') {
      parts.push(
        t('preassessment.statusLangReady', { lang: 'EN', count: local.en.questionCount }),
      );
    }
    if (parts.length === 0) return t('preassessment.statusNotGenerated');
    if (bothReady && local.fr.validated && local.en.validated)
      return t('preassessment.statusValidated');
    return parts.join(' · ');
  };

  const overallStatusColor = () => {
    if (isGenerating) return 'text-amber-600';
    if (local.fr.validated && local.en.validated) return 'text-green-700';
    if (anyReady) return 'text-teal-700';
    return 'text-muted-foreground';
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

  const renderQuestions = (questions: PreassessmentQuestion[]) => (
    <ol className="space-y-4">
      {questions.map((q, idx) => (
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
  );

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
                <span className={`flex items-center gap-1.5 text-sm font-medium ${overallStatusColor()}`}>
                  {isGenerating && (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
                  )}
                  {!isGenerating && (local.fr.validated || local.en.validated) && (
                    <CheckCircle2 className="h-3.5 w-3.5" aria-hidden="true" />
                  )}
                  {overallStatusLabel()}
                </span>
              </div>

              {isGenerating && (
                <div className="flex flex-wrap gap-2 text-xs text-muted-foreground">
                  {(['fr', 'en'] as Language[]).map((lang) => (
                    local[lang].status === 'generating' && (
                      <span key={lang} className="flex items-center gap-1 text-amber-600">
                        <Loader2 className="h-3 w-3 animate-spin" aria-hidden="true" />
                        {t('preassessment.generatingLang', { lang: lang.toUpperCase() })}
                      </span>
                    )
                  ))}
                </div>
              )}

              <div className="flex flex-wrap gap-2">
                <Button
                  size="sm"
                  variant="outline"
                  className="gap-1.5 min-h-11"
                  onClick={handleGenerate}
                  disabled={!ragIndexed || isGenerating}
                  title={!ragIndexed ? t('preassessment.ragNotIndexedTooltip') : undefined}
                  aria-label={t('preassessment.generateButton')}
                >
                  {isGenerating ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
                  ) : neitherGenerated ? (
                    <Sparkles className="h-3.5 w-3.5" aria-hidden="true" />
                  ) : (
                    <RefreshCw className="h-3.5 w-3.5" aria-hidden="true" />
                  )}
                  {neitherGenerated
                    ? t('preassessment.generateButton')
                    : t('preassessment.regenerateButton')}
                </Button>

                {(local.fr.status === 'ready' || local.fr.status === 'validated') && (
                  <Button
                    size="sm"
                    variant="ghost"
                    className="gap-1.5 min-h-11"
                    onClick={() => setPreviewLang((v) => (v === 'fr' ? null : 'fr'))}
                    aria-expanded={previewLang === 'fr'}
                  >
                    {previewLang === 'fr'
                      ? t('preassessment.hidePreviewLang', { lang: 'FR' })
                      : t('preassessment.showPreviewLang', { lang: 'FR' })}
                  </Button>
                )}

                {(local.en.status === 'ready' || local.en.status === 'validated') && (
                  <Button
                    size="sm"
                    variant="ghost"
                    className="gap-1.5 min-h-11"
                    onClick={() => setPreviewLang((v) => (v === 'en' ? null : 'en'))}
                    aria-expanded={previewLang === 'en'}
                  >
                    {previewLang === 'en'
                      ? t('preassessment.hidePreviewLang', { lang: 'EN' })
                      : t('preassessment.showPreviewLang', { lang: 'EN' })}
                  </Button>
                )}

                {anyReady && (
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
              </div>

              {error && (
                <div className="flex items-center gap-2 text-sm text-destructive" role="alert">
                  <AlertCircle className="h-4 w-4 shrink-0" aria-hidden="true" />
                  {error}
                </div>
              )}

              {previewLang && local[previewLang].questions.length > 0 && (
                <div className="space-y-3 rounded-lg border bg-muted/30 p-4">
                  <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
                    {t('preassessment.previewTitleLang', {
                      lang: previewLang.toUpperCase(),
                      count: local[previewLang].questions.length,
                    })}
                  </p>
                  {renderQuestions(local[previewLang].questions)}
                </div>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}
