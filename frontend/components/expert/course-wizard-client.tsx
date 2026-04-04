'use client';

import { useState, useCallback } from 'react';
import { useRouter } from 'next/navigation';
import { useTranslations, useLocale } from 'next-intl';
import {
  BookOpen,
  Sparkles,
  DollarSign,
  ClipboardCheck,
  ChevronLeft,
  ChevronRight,
  CheckCircle2,
  X,
  AlertCircle,
  Loader2,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Textarea } from '@/components/ui/textarea';
import { apiFetch } from '@/lib/api';

type WizardStep = 'metadata' | 'generate' | 'price' | 'review';

const STEPS: WizardStep[] = ['metadata', 'generate', 'price', 'review'];

const DOMAIN_OPTIONS = [
  'health_sciences', 'natural_sciences', 'social_sciences',
  'mathematics', 'engineering', 'information_technology',
  'education', 'arts_humanities', 'business_management',
  'law', 'agriculture', 'environmental_studies', 'other',
] as const;

const LEVEL_OPTIONS = [
  'beginner', 'intermediate', 'advanced', 'expert',
] as const;

const AUDIENCE_OPTIONS = [
  'kindergarten', 'primary_school', 'secondary_school',
  'university', 'professional', 'researcher',
  'teacher', 'policy_maker', 'continuing_education',
] as const;

interface CourseMetadata {
  title_fr: string;
  title_en: string;
  description_fr: string;
  description_en: string;
  course_domain: string[];
  course_level: string[];
  audience_type: string[];
  estimated_hours: number;
  cover_image_url: string;
}

interface GeneratedModule {
  id: string;
  module_number: number;
  title_fr: string;
  title_en: string;
}

interface CourseWizardClientProps {
  onClose?: () => void;
}

function MultiSelectChips({
  label,
  id,
  options,
  selected,
  onToggle,
  tKey,
  tTax,
}: {
  label: string;
  id: string;
  options: readonly string[];
  selected: string[];
  onToggle: (val: string) => void;
  tKey: string;
  tTax: (key: string) => string;
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <Label htmlFor={id}>{label}</Label>
      <div className="flex flex-wrap gap-1.5" id={id}>
        {options.map((opt) => {
          const isSelected = selected.includes(opt);
          return (
            <button
              key={opt}
              type="button"
              onClick={() => onToggle(opt)}
              className={`inline-flex items-center rounded-full px-2.5 py-1 text-xs font-medium transition-colors min-h-[32px] ${
                isSelected
                  ? 'bg-teal-600 text-white hover:bg-teal-700'
                  : 'bg-stone-100 text-stone-600 hover:bg-stone-200 border border-stone-200'
              }`}
            >
              {tTax(`${tKey}.${opt}`)}
            </button>
          );
        })}
      </div>
    </div>
  );
}

export function ExpertCourseWizardClient({ onClose }: CourseWizardClientProps) {
  const t = useTranslations('ExpertCourses.wizard');
  const tCourses = useTranslations('ExpertCourses');
  const tTax = useTranslations('Taxonomy');
  const locale = useLocale();
  const router = useRouter();

  const [step, setStep] = useState<WizardStep>('metadata');
  const stepIndex = STEPS.indexOf(step);

  const [metadata, setMetadata] = useState<CourseMetadata>({
    title_fr: '',
    title_en: '',
    description_fr: '',
    description_en: '',
    course_domain: [],
    course_level: [],
    audience_type: [],
    estimated_hours: 20,
    cover_image_url: '',
  });
  const [metadataErrors, setMetadataErrors] = useState<Partial<Record<string, string>>>({});

  const [courseId, setCourseId] = useState<string | null>(null);
  const [generatedModules, setGeneratedModules] = useState<GeneratedModule[]>([]);
  const [isGenerating, setIsGenerating] = useState(false);
  const [generateError, setGenerateError] = useState<string | null>(null);

  const [isFree, setIsFree] = useState(true);
  const [price, setPrice] = useState<number>(0);

  const [isSaving, setIsSaving] = useState(false);
  const [saveSuccess, setSaveSuccess] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  const toggleArray = (arr: string[], val: string): string[] =>
    arr.includes(val) ? arr.filter((v) => v !== val) : [...arr, val];

  const handleNextFromMetadata = useCallback(() => {
    const errors: Record<string, string> = {};
    if (!metadata.title_fr.trim()) errors.title_fr = tCourses('fieldRequired');
    if (!metadata.title_en.trim()) errors.title_en = tCourses('fieldRequired');
    if (Object.keys(errors).length > 0) {
      setMetadataErrors(errors);
      return;
    }
    setMetadataErrors({});
    setStep('generate');
  }, [metadata, tCourses]);

  const generateStructure = useCallback(async () => {
    setIsGenerating(true);
    setGenerateError(null);
    try {
      let id = courseId;
      if (!id) {
        const course = await apiFetch<{ id: string }>('/api/v1/expert/courses', {
          method: 'POST',
          body: JSON.stringify({
            title_fr: metadata.title_fr,
            title_en: metadata.title_en,
            description_fr: metadata.description_fr || undefined,
            description_en: metadata.description_en || undefined,
            course_domain: metadata.course_domain,
            course_level: metadata.course_level,
            audience_type: metadata.audience_type,
            estimated_hours: metadata.estimated_hours,
            cover_image_url: metadata.cover_image_url || undefined,
          }),
        });
        id = course.id;
        setCourseId(id);
      }
      const result = await apiFetch<{ modules: GeneratedModule[]; count: number }>(
        `/api/v1/expert/courses/${id}/generate-structure`,
        {
          method: 'POST',
          body: JSON.stringify({ estimated_hours: metadata.estimated_hours }),
        }
      );
      setGeneratedModules(result.modules);
    } catch {
      setGenerateError(t('generate.error'));
    } finally {
      setIsGenerating(false);
    }
  }, [courseId, metadata, t]);

  const handleSaveAsDraft = useCallback(async () => {
    setIsSaving(true);
    setSaveError(null);
    try {
      let id = courseId;
      if (!id) {
        const course = await apiFetch<{ id: string }>('/api/v1/expert/courses', {
          method: 'POST',
          body: JSON.stringify({
            title_fr: metadata.title_fr,
            title_en: metadata.title_en,
            description_fr: metadata.description_fr || undefined,
            description_en: metadata.description_en || undefined,
            course_domain: metadata.course_domain,
            course_level: metadata.course_level,
            audience_type: metadata.audience_type,
            estimated_hours: metadata.estimated_hours,
            cover_image_url: metadata.cover_image_url || undefined,
          }),
        });
        id = course.id;
        setCourseId(id);
      } else {
        await apiFetch(`/api/v1/expert/courses/${id}`, {
          method: 'PATCH',
          body: JSON.stringify({ price_credits: isFree ? 0 : price }),
        });
      }
      setSaveSuccess(true);
      setTimeout(() => {
        router.push(`/${locale}/expert/courses/${id}`);
      }, 1500);
    } catch {
      setSaveError(t('review.error'));
    } finally {
      setIsSaving(false);
    }
  }, [courseId, metadata, price, isFree, locale, router, t]);

  const canGoNext = (): boolean => {
    if (step === 'metadata') {
      return !!metadata.title_fr.trim() && !!metadata.title_en.trim();
    }
    if (step === 'generate') {
      return generatedModules.length > 0;
    }
    return true;
  };

  const handleNext = () => {
    if (step === 'metadata') {
      handleNextFromMetadata();
      return;
    }
    const idx = STEPS.indexOf(step);
    if (idx < STEPS.length - 1) setStep(STEPS[idx + 1]);
  };

  const handleBack = () => {
    const idx = STEPS.indexOf(step);
    if (idx > 0) setStep(STEPS[idx - 1]);
  };

  const stepIcons: Record<WizardStep, React.ReactNode> = {
    metadata: <BookOpen className="h-4 w-4" />,
    generate: <Sparkles className="h-4 w-4" />,
    price: <DollarSign className="h-4 w-4" />,
    review: <ClipboardCheck className="h-4 w-4" />,
  };

  return (
    <div className="fixed inset-0 z-50 flex flex-col bg-background">
      <div className="flex items-center justify-between border-b px-4 py-3 shrink-0">
        <h2 className="text-lg font-semibold">{t('title')}</h2>
        {onClose && (
          <Button variant="ghost" size="icon" onClick={onClose} aria-label={t('close')}>
            <X className="h-5 w-5" />
          </Button>
        )}
      </div>

      <div className="border-b px-4 py-3 shrink-0">
        <div className="flex items-center gap-1 overflow-x-auto">
          {STEPS.map((s, i) => (
            <div key={s} className="flex items-center gap-1 shrink-0">
              <div
                className={`flex items-center gap-1.5 rounded-full px-3 py-1.5 text-xs font-medium transition-colors ${
                  s === step
                    ? 'bg-primary text-primary-foreground'
                    : i < stepIndex
                    ? 'bg-primary/20 text-primary'
                    : 'bg-muted text-muted-foreground'
                }`}
              >
                {i < stepIndex ? (
                  <CheckCircle2 className="h-3.5 w-3.5" />
                ) : (
                  stepIcons[s]
                )}
                <span className="hidden sm:inline">{t(`steps.${s}`)}</span>
              </div>
              {i < STEPS.length - 1 && (
                <div className={`h-px w-4 ${i < stepIndex ? 'bg-primary/40' : 'bg-border'}`} />
              )}
            </div>
          ))}
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-4 md:p-6">
        <div className="mx-auto max-w-2xl space-y-6">

          {step === 'metadata' && (
            <div className="space-y-4">
              <div>
                <h3 className="text-xl font-semibold">{t('metadata.title')}</h3>
                <p className="mt-1 text-sm text-muted-foreground">{t('metadata.description')}</p>
              </div>

              <div className="space-y-1.5">
                <Label htmlFor="title_fr">{tCourses('titleFr')} *</Label>
                <Input
                  id="title_fr"
                  value={metadata.title_fr}
                  onChange={(e) => setMetadata((p) => ({ ...p, title_fr: e.target.value }))}
                  placeholder={tCourses('titleFrPlaceholder')}
                  className={`min-h-11 ${metadataErrors.title_fr ? 'border-destructive' : ''}`}
                  aria-invalid={!!metadataErrors.title_fr}
                />
                {metadataErrors.title_fr && (
                  <p className="text-xs text-destructive">{metadataErrors.title_fr}</p>
                )}
              </div>

              <div className="space-y-1.5">
                <Label htmlFor="title_en">{tCourses('titleEn')} *</Label>
                <Input
                  id="title_en"
                  value={metadata.title_en}
                  onChange={(e) => setMetadata((p) => ({ ...p, title_en: e.target.value }))}
                  placeholder={tCourses('titleEnPlaceholder')}
                  className={`min-h-11 ${metadataErrors.title_en ? 'border-destructive' : ''}`}
                  aria-invalid={!!metadataErrors.title_en}
                />
                {metadataErrors.title_en && (
                  <p className="text-xs text-destructive">{metadataErrors.title_en}</p>
                )}
              </div>

              <div className="space-y-1.5">
                <Label htmlFor="desc_fr">{tCourses('descriptionFr')}</Label>
                <Textarea
                  id="desc_fr"
                  value={metadata.description_fr}
                  onChange={(e) => setMetadata((p) => ({ ...p, description_fr: e.target.value }))}
                  placeholder={tCourses('descriptionFrPlaceholder')}
                  rows={3}
                />
              </div>

              <div className="space-y-1.5">
                <Label htmlFor="desc_en">{tCourses('descriptionEn')}</Label>
                <Textarea
                  id="desc_en"
                  value={metadata.description_en}
                  onChange={(e) => setMetadata((p) => ({ ...p, description_en: e.target.value }))}
                  placeholder={tCourses('descriptionEnPlaceholder')}
                  rows={3}
                />
              </div>

              <MultiSelectChips
                label={tCourses('domain')}
                id="course-domain"
                options={DOMAIN_OPTIONS}
                selected={metadata.course_domain}
                onToggle={(v) => setMetadata((p) => ({ ...p, course_domain: toggleArray(p.course_domain, v) }))}
                tKey="domains"
                tTax={(k) => tTax(k)}
              />

              <MultiSelectChips
                label={tCourses('level')}
                id="course-level"
                options={LEVEL_OPTIONS}
                selected={metadata.course_level}
                onToggle={(v) => setMetadata((p) => ({ ...p, course_level: toggleArray(p.course_level, v) }))}
                tKey="levels"
                tTax={(k) => tTax(k)}
              />

              <MultiSelectChips
                label={tCourses('audience')}
                id="course-audience"
                options={AUDIENCE_OPTIONS}
                selected={metadata.audience_type}
                onToggle={(v) => setMetadata((p) => ({ ...p, audience_type: toggleArray(p.audience_type, v) }))}
                tKey="audience_types"
                tTax={(k) => tTax(k)}
              />

              <div className="space-y-1.5">
                <Label htmlFor="estimated_hours">{tCourses('estimatedHoursField')}</Label>
                <Input
                  id="estimated_hours"
                  type="number"
                  min={1}
                  max={500}
                  value={metadata.estimated_hours}
                  onChange={(e) =>
                    setMetadata((p) => ({ ...p, estimated_hours: parseInt(e.target.value) || 20 }))
                  }
                  className="min-h-11"
                />
              </div>

              <div className="space-y-1.5">
                <Label htmlFor="cover_image">{tCourses('coverImageUrl')}</Label>
                <Input
                  id="cover_image"
                  value={metadata.cover_image_url}
                  onChange={(e) => setMetadata((p) => ({ ...p, cover_image_url: e.target.value }))}
                  placeholder="https://..."
                  className="min-h-11"
                />
              </div>
            </div>
          )}

          {step === 'generate' && (
            <div className="space-y-4">
              <div>
                <h3 className="text-xl font-semibold">{t('generate.title')}</h3>
                <p className="mt-1 text-sm text-muted-foreground">{t('generate.description')}</p>
                <p className="mt-1 text-xs text-amber-600 font-medium">
                  {t('generate.creditEstimate', { credits: Math.ceil(metadata.estimated_hours * 2) })}
                </p>
              </div>

              {generatedModules.length === 0 && !isGenerating && (
                <Button
                  onClick={generateStructure}
                  className="w-full min-h-11 gap-2"
                  disabled={isGenerating}
                >
                  <Sparkles className="h-4 w-4" />
                  {t('generate.button')}
                </Button>
              )}

              {isGenerating && (
                <div className="flex flex-col items-center gap-3 py-8">
                  <Loader2 className="h-8 w-8 animate-spin text-primary" />
                  <p className="text-sm text-muted-foreground">{t('generate.generating')}</p>
                </div>
              )}

              {generateError && (
                <div className="flex items-center gap-2 rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
                  <AlertCircle className="h-4 w-4 shrink-0" />
                  {generateError}
                </div>
              )}

              {generatedModules.length > 0 && (
                <div className="space-y-3">
                  <div className="flex items-center gap-2">
                    <CheckCircle2 className="h-4 w-4 text-green-600" />
                    <p className="text-sm font-medium text-green-700">
                      {t('generate.moduleCount', { count: generatedModules.length })}
                    </p>
                  </div>
                  <div className="space-y-2 max-h-80 overflow-y-auto">
                    {generatedModules.map((m) => (
                      <div
                        key={m.id}
                        className="flex items-center gap-3 rounded-lg border bg-card p-3"
                      >
                        <Badge variant="outline" className="shrink-0 text-xs">
                          M{m.module_number}
                        </Badge>
                        <div className="min-w-0">
                          <p className="truncate text-sm font-medium">{m.title_fr}</p>
                          <p className="truncate text-xs text-muted-foreground">{m.title_en}</p>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}

          {step === 'price' && (
            <div className="space-y-4">
              <div>
                <h3 className="text-xl font-semibold">{t('price.title')}</h3>
                <p className="mt-1 text-sm text-muted-foreground">{t('price.description')}</p>
              </div>

              <div className="flex gap-3">
                <button
                  type="button"
                  onClick={() => setIsFree(true)}
                  className={`flex-1 rounded-xl border-2 p-4 text-left transition-colors min-h-[64px] ${
                    isFree ? 'border-primary bg-primary/5' : 'border-border hover:border-primary/50'
                  }`}
                >
                  <p className="font-semibold text-sm">{t('price.free')}</p>
                  <p className="text-xs text-muted-foreground mt-0.5">0 crédits</p>
                </button>
                <button
                  type="button"
                  onClick={() => setIsFree(false)}
                  className={`flex-1 rounded-xl border-2 p-4 text-left transition-colors min-h-[64px] ${
                    !isFree ? 'border-primary bg-primary/5' : 'border-border hover:border-primary/50'
                  }`}
                >
                  <p className="font-semibold text-sm">{t('price.paid')}</p>
                  <p className="text-xs text-muted-foreground mt-0.5">{t('price.pricePlaceholder')}</p>
                </button>
              </div>

              {!isFree && (
                <div className="space-y-1.5">
                  <Label htmlFor="price_credits">{t('price.priceLabel')}</Label>
                  <Input
                    id="price_credits"
                    type="number"
                    min={1}
                    value={price || ''}
                    onChange={(e) => setPrice(parseInt(e.target.value) || 0)}
                    placeholder={t('price.pricePlaceholder')}
                    className="min-h-11"
                  />
                </div>
              )}
            </div>
          )}

          {step === 'review' && (
            <div className="space-y-4">
              <div>
                <h3 className="text-xl font-semibold">{t('review.title')}</h3>
                <p className="mt-1 text-sm text-muted-foreground">{t('review.description')}</p>
              </div>

              <Card>
                <CardHeader>
                  <CardTitle className="text-base">{t('review.summaryTitle')}</CardTitle>
                </CardHeader>
                <CardContent className="space-y-2 text-sm">
                  <div className="flex justify-between gap-2">
                    <span className="text-muted-foreground shrink-0">Titre (FR)</span>
                    <span className="font-medium truncate">{metadata.title_fr}</span>
                  </div>
                  <div className="flex justify-between gap-2">
                    <span className="text-muted-foreground shrink-0">Title (EN)</span>
                    <span className="font-medium truncate">{metadata.title_en}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-muted-foreground">{t('review.hours')}</span>
                    <span className="font-medium">{metadata.estimated_hours}h</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-muted-foreground">{t('review.modules')}</span>
                    <span className="font-medium">{generatedModules.length}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-muted-foreground">{t('review.price')}</span>
                    <span className="font-medium">
                      {isFree ? tCourses('priceFree') : `${price} crédits`}
                    </span>
                  </div>
                </CardContent>
              </Card>

              {saveSuccess ? (
                <div className="flex flex-col items-center gap-3 py-4 text-center">
                  <CheckCircle2 className="h-12 w-12 text-green-600" />
                  <div>
                    <p className="font-semibold text-green-700">{t('review.success')}</p>
                    <p className="text-sm text-muted-foreground">{t('review.successDesc')}</p>
                  </div>
                </div>
              ) : (
                <>
                  {saveError && (
                    <div className="flex items-center gap-2 rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
                      <AlertCircle className="h-4 w-4 shrink-0" />
                      {saveError}
                    </div>
                  )}
                  <Button
                    onClick={handleSaveAsDraft}
                    className="w-full min-h-11 gap-2"
                    disabled={isSaving}
                  >
                    {isSaving ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : (
                      <ClipboardCheck className="h-4 w-4" />
                    )}
                    {isSaving ? t('review.saving') : t('review.saveAsDraft')}
                  </Button>
                </>
              )}
            </div>
          )}
        </div>
      </div>

      {!saveSuccess && (
        <div className="flex items-center justify-between border-t bg-background px-4 py-3 shrink-0">
          <Button
            variant="outline"
            onClick={handleBack}
            disabled={stepIndex === 0}
            className="min-h-11"
          >
            <ChevronLeft className="mr-1 h-4 w-4" />
            {t('back')}
          </Button>

          {step !== 'review' && (
            <Button
              onClick={handleNext}
              disabled={!canGoNext() || isGenerating}
              className="min-h-11"
            >
              {t('next')}
              <ChevronRight className="ml-1 h-4 w-4" />
            </Button>
          )}
        </div>
      )}
    </div>
  );
}
