import { getTranslations } from 'next-intl/server';
import { notFound } from 'next/navigation';
import { getLocale } from 'next-intl/server';
import { Link } from '@/i18n/routing';
import { ChevronLeft, Clock, CheckCircle, Lock, BookOpen } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { getModuleById, getPrerequisiteModules, isModuleUnlocked } from '@/lib/modules';
import { ModuleProgressOverlay } from '@/components/learning/module-progress-overlay';

interface ModuleOverviewPageProps {
  params: Promise<{ moduleId: string }>;
}

export default async function ModuleOverviewPage({ params }: ModuleOverviewPageProps) {
  const { moduleId } = await params;
  const locale = await getLocale();
  const t = await getTranslations('ModuleOverview');
  
  const moduleData = getModuleById(moduleId);
  
  if (!moduleData) {
    notFound();
  }

  const prerequisites = getPrerequisiteModules(moduleData);
  const isUnlocked = isModuleUnlocked(moduleData);
  const language = locale as 'en' | 'fr';

  if (!isUnlocked) {
    return (
      <div className="container mx-auto max-w-4xl px-4 py-6">
        {/* Breadcrumb */}
        <div className="mb-6">
          <Link href="/modules" className="inline-flex items-center text-stone-600 hover:text-stone-900 transition-colors">
            <ChevronLeft className="w-4 h-4 mr-1" />
            {t('backToModules')}
          </Link>
        </div>

        {/* Locked Module */}
        <div className="text-center py-12">
          <div className="mx-auto w-20 h-20 bg-stone-100 rounded-full flex items-center justify-center mb-6">
            <Lock className="w-10 h-10 text-stone-400" />
          </div>
          <h1 className="text-2xl font-bold text-stone-900 mb-2">{t('locked')}</h1>
          <p className="text-stone-600 mb-8">{t('lockedDescription')}</p>
          
          {/* Prerequisites */}
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
      {/* Breadcrumb */}
      <div className="mb-6">
        <Link href="/modules" className="inline-flex items-center text-stone-600 hover:text-stone-900 transition-colors">
          <ChevronLeft className="w-4 h-4 mr-1" />
          {t('backToModules')}
        </Link>
      </div>

      {/* Module Header */}
      <div className="mb-8">
        <div className="flex items-center gap-3 mb-3">
          <Badge variant="outline">{t('level', { level: moduleData.level })}</Badge>
          <div className="flex items-center text-stone-600">
            <Clock className="w-4 h-4 mr-1" />
            {t('hours', { count: moduleData.estimatedHours })}
          </div>
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
        {/* Main Content */}
        <div className="md:col-span-2 space-y-8">
          {/* Learning Objectives */}
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

          {/* Progress and Units — fetches real data from API, falls back gracefully */}
          <ModuleProgressOverlay
            moduleId={moduleId}
            staticCompletionPercentage={moduleData.completionPercentage}
            staticUnits={moduleData.units}
          />
        </div>

        {/* Sidebar Actions */}
        <div className="space-y-4">
          <div className="space-y-2">
            <Button variant="outline" className="w-full min-h-11">
              <BookOpen className="w-4 h-4 mr-2" />
              {t('viewFlashcards')}
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}