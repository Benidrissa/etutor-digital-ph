'use client';

import { useEffect, useState } from 'react';
import { useTranslations } from 'next-intl';
import { Link } from '@/i18n/routing';
import { ChevronLeft, Lock, BookOpen, CheckCircle, Clock } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { getModuleProgress } from '@/lib/api';
import { useCurrentUser } from '@/lib/hooks/use-current-user';
import { ModuleMediaSection } from '@/components/learning/module-media-section';
import { ModuleProgressOverlay } from '@/components/learning/module-progress-overlay';
import type { Module } from '@/lib/modules';

interface ModuleLockGateProps {
  moduleId: string;
  moduleData: Module;
  prerequisites: Module[];
  language: 'en' | 'fr';
}

export function ModuleLockGate({ moduleId, moduleData, prerequisites, language }: ModuleLockGateProps) {
  const t = useTranslations('ModuleOverview');
  const tCard = useTranslations('ModuleCard');
  const currentUser = useCurrentUser();
  const [status, setStatus] = useState<'locked' | 'in_progress' | 'completed' | 'loading'>('loading');
  const isAdmin = (currentUser as { role?: string } | null)?.role === 'admin';

  useEffect(() => {
    let cancelled = false;
    getModuleProgress(moduleId)
      .then((res) => {
        if (!cancelled) setStatus(res.status);
      })
      .catch(() => {
        if (!cancelled) {
          const fallback = moduleData.status === 'in-progress' ? 'in_progress' : moduleData.status as 'locked' | 'completed';
          setStatus(fallback);
        }
      });
    return () => { cancelled = true; };
  }, [moduleId, moduleData.status]);

  if (status === 'loading') {
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

          <Card className="max-w-md mx-auto">
            <CardHeader>
              <CardTitle className="text-lg">{t('prerequisites')}</CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-sm text-stone-600 mb-4">{t('prerequisitesDescription')}</p>
              <div className="space-y-2">
                {prerequisites.map((prereq) => (
                  <div key={prereq.id} className="flex items-center justify-between p-3 bg-stone-50 rounded-lg">
                    <span className="text-sm font-medium">{prereq.title[language]}</span>
                    <Badge variant={prereq.status === 'completed' ? 'default' : 'secondary'}>
                      {prereq.status === 'completed' ? '✓' : '○'}
                    </Badge>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
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
          <Badge variant="outline">{t('level', { level: moduleData.level })}</Badge>
          <div className="flex items-center text-stone-600">
            <Clock className="w-4 h-4 mr-1" />
            {t('hours', { count: moduleData.estimatedHours })}
          </div>
          {status === 'completed' && (
            <div className="flex items-center text-teal-600">
              <CheckCircle className="w-4 h-4 mr-1" />
              <span className="text-sm font-medium">{tCard('completed')}</span>
            </div>
          )}
        </div>
        <h1 className="text-3xl font-bold text-stone-900 mb-3">
          {moduleData.title[language]}
        </h1>
        {moduleData.description && (
          <p className="text-lg text-stone-600 leading-relaxed">
            {moduleData.description[language]}
          </p>
        )}
      </div>

      <div className="grid md:grid-cols-3 gap-8">
        <div className="md:col-span-2 space-y-8">
          <ModuleMediaSection
            moduleId={moduleId}
            language={language}
            isAdmin={isAdmin}
          />

          {moduleData.learningObjectives && (
            <Card>
              <CardHeader>
                <CardTitle>{t('learningObjectives')}</CardTitle>
              </CardHeader>
              <CardContent>
                <ul className="space-y-3">
                  {moduleData.learningObjectives[language].map((objective, index) => (
                    <li key={index} className="flex items-start gap-3">
                      <CheckCircle className="w-5 h-5 text-teal-600 mt-0.5 flex-shrink-0" />
                      <span className="text-stone-700">{objective}</span>
                    </li>
                  ))}
                </ul>
              </CardContent>
            </Card>
          )}

          <ModuleProgressOverlay
            moduleId={moduleId}
            staticCompletionPercentage={moduleData.completionPercentage}
            staticUnits={moduleData.units}
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
        </div>
      </div>
    </div>
  );
}
