'use client';

import { useEffect, useRef, useState } from 'react';
import { useTranslations } from 'next-intl';
import { Link } from '@/i18n/routing';
import { ChevronLeft, Lock, BookOpen, CheckCircle, Clock } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { getModuleDetailWithProgress, getModuleUnits, type ModuleDetailWithProgressResponse } from '@/lib/api';
import { track } from '@/lib/analytics';
import { ModuleProgressOverlay } from '@/components/learning/module-progress-overlay';
// ModuleMediaPlayer removed in #1802: per-module audio/video was
// rescoped to per-lesson. Lesson-level players are embedded in
// lesson-viewer.tsx directly.
import { DownloadModuleButton } from '@/components/learning/download-module-button';

interface ModuleLockGateProps {
  moduleId: string;
  language: 'en' | 'fr';
}

export function ModuleLockGate({ moduleId, language }: ModuleLockGateProps) {
  const t = useTranslations('ModuleOverview');
  const tCard = useTranslations('ModuleCard');
  const [moduleData, setModuleData] = useState<ModuleDetailWithProgressResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const unlockedTracked = useRef(false);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        const data = await getModuleDetailWithProgress(moduleId);
        if (!cancelled) {
          setModuleData(data);
          setLoading(false);
          if (data.status !== 'locked' && !unlockedTracked.current) {
            unlockedTracked.current = true;
            track('module_unlocked', {
              module_id: data.id,
              level: data.level,
            });
          }
        }
      } catch {
        try {
          const pub = await getModuleUnits(moduleId);
          if (!cancelled) {
            setModuleData({
              id: pub.module_id,
              module_number: pub.module_number,
              level: pub.level,
              title_fr: pub.title_fr,
              title_en: pub.title_en,
              description_fr: pub.description_fr,
              description_en: pub.description_en,
              estimated_hours: pub.estimated_hours,
              prereq_modules: [],
              status: 'locked',
              completion_pct: 0,
              quiz_score_avg: null,
              time_spent_minutes: 0,
              last_accessed: null,
              units: pub.units.map((u) => ({
                id: u.id,
                unit_number: u.unit_number,
                title_fr: u.title_fr,
                title_en: u.title_en,
                description_fr: u.description_fr,
                description_en: u.description_en,
                estimated_minutes: u.estimated_minutes,
                order_index: u.order_index,
                status: 'pending',
              })),
            });
            setLoading(false);
          }
        } catch {
          if (!cancelled) setLoading(false);
        }
      }
    }

    load();
    return () => { cancelled = true; };
  }, [moduleId]);

  const status = moduleData?.status ?? 'locked';

  if (loading) {
    return (
      <div className="container mx-auto max-w-4xl px-4 py-6">
        <div className="mb-6">
          <Link href="/modules" className="inline-flex items-center text-stone-600 hover:text-stone-900 transition-colors">
            <ChevronLeft className="w-4 h-4 mr-1" />
            {t('backToModules')}
          </Link>
        </div>
        <div className="animate-pulse space-y-4">
          <div className="h-8 bg-stone-200 rounded w-1/3" />
          <div className="h-4 bg-stone-200 rounded w-2/3" />
          <div className="h-4 bg-stone-200 rounded w-1/2" />
        </div>
      </div>
    );
  }

  const title = language === 'fr' ? (moduleData?.title_fr ?? '') : (moduleData?.title_en ?? '');
  const description = language === 'fr' ? moduleData?.description_fr : moduleData?.description_en;

  if (status === 'locked') {
    return (
      <div className="container mx-auto max-w-4xl px-4 py-6">
        <div className="mb-6">
          <Link href="/modules" className="inline-flex items-center text-stone-600 hover:text-stone-900 transition-colors">
            <ChevronLeft className="w-4 h-4 mr-1" />
            {t('backToModules')}
          </Link>
        </div>

        <div className="text-center py-12">
          <div className="mx-auto w-20 h-20 bg-stone-100 rounded-full flex items-center justify-center mb-6">
            <Lock className="w-10 h-10 text-stone-400" />
          </div>
          <h1 className="text-2xl font-bold text-stone-900 mb-2">{t('locked')}</h1>
          <p className="text-stone-600 mb-8">{t('lockedDescription')}</p>

          {(moduleData?.prereq_modules ?? []).length > 0 && (
            <Card className="max-w-md mx-auto">
              <CardHeader>
                <CardTitle className="text-lg">{t('prerequisites')}</CardTitle>
              </CardHeader>
              <CardContent>
                <p className="text-sm text-stone-600 mb-4">{t('prerequisitesDescription')}</p>
                <div className="space-y-2">
                  {(moduleData?.prereq_modules ?? []).map((prereqId) => (
                    <div key={prereqId} className="flex items-center justify-between p-3 bg-stone-50 rounded-lg">
                      <span className="text-sm font-medium">{prereqId}</span>
                      <Badge variant="secondary">○</Badge>
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="container mx-auto max-w-4xl px-4 py-6">
      <div className="mb-6">
        <Link href="/modules" className="inline-flex items-center text-stone-600 hover:text-stone-900 transition-colors">
          <ChevronLeft className="w-4 h-4 mr-1" />
          {t('backToModules')}
        </Link>
      </div>

      <div className="mb-8">
        <div className="flex items-center gap-3 mb-3">
          {moduleData && (
            <Badge variant="outline">{t('level', { level: moduleData.level })}</Badge>
          )}
          {moduleData && (
            <div className="flex items-center text-stone-600">
              <Clock className="w-4 h-4 mr-1" />
              {t('hours', { count: moduleData.estimated_hours })}
            </div>
          )}
          {status === 'completed' && (
            <div className="flex items-center text-teal-600">
              <CheckCircle className="w-4 h-4 mr-1" />
              <span className="text-sm font-medium">{tCard('completed')}</span>
            </div>
          )}
        </div>
        <h1 className="text-3xl font-bold text-stone-900 mb-3">
          {title}
        </h1>
        {description && (
          <p className="text-lg text-stone-600 leading-relaxed">
            {description}
          </p>
        )}
      </div>

      <div className="grid md:grid-cols-3 gap-8">
        <div className="md:col-span-2 space-y-8">
          <ModuleProgressOverlay
            moduleId={moduleId}
            staticCompletionPercentage={moduleData?.completion_pct ?? 0}
          />
        </div>

        <div className="space-y-4">
          <div className="space-y-2">
            {status === 'completed' && (
              <Link href={`/modules/${moduleId}/quiz`} className="block">
                <Button className="w-full min-h-11 bg-teal-600 hover:bg-teal-700">
                  <CheckCircle className="w-4 h-4 mr-2" />
                  {tCard('review')}
                </Button>
              </Link>
            )}
            <Link href={{ pathname: '/flashcards', query: { module: moduleId } }} className="block">
              <Button variant="outline" className="w-full min-h-11">
                <BookOpen className="w-4 h-4 mr-2" />
                {t('viewFlashcards')}
              </Button>
            </Link>
          </div>

          <DownloadModuleButton
            moduleId={moduleId}
            locale={language}
            unitCount={moduleData?.units?.length ?? 0}
            level={moduleData?.level}
          />
        </div>
      </div>
    </div>
  );
}
