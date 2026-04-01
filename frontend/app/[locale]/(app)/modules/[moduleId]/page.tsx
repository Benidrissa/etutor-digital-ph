import { getTranslations } from 'next-intl/server';
import { notFound } from 'next/navigation';
import { getLocale } from 'next-intl/server';
import { Link } from '@/i18n/routing';
import { ChevronLeft, Clock, CheckCircle, Circle, Lock, Play, BookOpen, MessageSquare, FileText } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Progress } from '@/components/ui/progress';
import { Badge } from '@/components/ui/badge';
import { getModuleById, getPrerequisiteModules, isModuleUnlocked } from '@/lib/modules';
import { API_BASE } from '@/lib/api';

interface ModuleOverviewPageProps {
  params: Promise<{ moduleId: string }>;
}

interface ApiUnit {
  id: string;
  module_id: string;
  unit_number: string;
  title_fr: string;
  title_en: string;
  description_fr: string | null;
  description_en: string | null;
  estimated_minutes: number;
  order_index: number;
  unit_type: 'lesson' | 'quiz' | 'case-study';
  books_sources: Record<string, string[]> | null;
}

interface ApiUnitsResponse {
  module_id: string;
  units: ApiUnit[];
  total: number;
}

async function getModuleUnits(moduleId: string): Promise<ApiUnit[]> {
  try {
    const res = await fetch(`${API_BASE}/api/v1/modules/${moduleId}/units`, {
      next: { revalidate: 3600 },
    });
    if (!res.ok) return [];
    const data: ApiUnitsResponse = await res.json();
    return data.units ?? [];
  } catch {
    return [];
  }
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

  const apiUnits = await getModuleUnits(moduleId);

  const units = apiUnits.length > 0
    ? apiUnits.map((u) => ({
        id: u.unit_number,
        number: u.order_index,
        title: { fr: u.title_fr, en: u.title_en },
        description: (u.description_fr || u.description_en)
          ? { fr: u.description_fr ?? '', en: u.description_en ?? '' }
          : undefined,
        status: 'pending' as const,
        estimatedMinutes: u.estimated_minutes,
        type: u.unit_type,
      }))
    : (moduleData.units ?? []);

  const getStatusIcon = (status: 'pending' | 'in-progress' | 'completed') => {
    switch (status) {
      case 'completed':
        return <CheckCircle className="w-5 h-5 text-green-600" />;
      case 'in-progress':
        return <Circle className="w-5 h-5 text-blue-600 fill-blue-100" />;
      case 'pending':
        return <Circle className="w-5 h-5 text-stone-400" />;
    }
  };

  const getTypeIcon = (type: 'lesson' | 'quiz' | 'case-study') => {
    switch (type) {
      case 'lesson':
        return <BookOpen className="w-4 h-4" />;
      case 'quiz':
        return <MessageSquare className="w-4 h-4" />;
      case 'case-study':
        return <FileText className="w-4 h-4" />;
    }
  };

  const completedUnits = units.filter((unit) => unit.status === 'completed').length;
  const totalUnits = units.length;
  const nextUnit = units.find((unit) => unit.status === 'in-progress' || unit.status === 'pending');

  if (!isUnlocked) {
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

      <Card className="mb-8">
        <CardHeader>
          <CardTitle className="flex items-center justify-between">
            <span>{t('progress')}</span>
            <span className="text-lg font-bold text-teal-600">
              {t('progressPercent', { percent: moduleData.completionPercentage })}
            </span>
          </CardTitle>
        </CardHeader>
        <CardContent>
          <Progress value={moduleData.completionPercentage} className="mb-4 h-2" />
          <p className="text-sm text-stone-600">
            {t('unitsCompleted', { completed: completedUnits, total: totalUnits })}
          </p>
        </CardContent>
      </Card>

      <div className="grid md:grid-cols-3 gap-8">
        <div className="md:col-span-2 space-y-8">
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

          {units.length > 0 && (
            <Card>
              <CardHeader>
                <CardTitle>{t('units')}</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="space-y-3">
                  {units.map((unit) => (
                    <Link
                      key={unit.id}
                      href={unit.type === 'quiz' ? `/modules/${moduleId}/quiz?unit=${unit.id}` : `/modules/${moduleId}/lessons/${unit.id}`}
                      className="block"
                    >
                      <div className="flex items-center gap-4 p-4 border border-stone-200 rounded-lg hover:border-stone-300 hover:bg-stone-50 transition-colors cursor-pointer">
                        <div className="flex items-center gap-3 flex-1">
                          {getStatusIcon(unit.status)}
                          <div className="flex items-center gap-2 text-stone-600">
                            {getTypeIcon(unit.type)}
                            <span className="text-sm font-medium">
                              {t('unitNumber', { number: unit.number })}
                            </span>
                          </div>
                          <div className="flex-1">
                            <h4 className="font-medium text-stone-900">{unit.title[language]}</h4>
                            {unit.description && (
                              <p className="text-sm text-stone-600 mt-1">{unit.description[language]}</p>
                            )}
                          </div>
                          <div className="flex items-center gap-2 text-sm text-stone-500">
                            <Clock className="w-4 h-4" />
                            {t('readingTime', { minutes: unit.estimatedMinutes })}
                          </div>
                        </div>
                      </div>
                    </Link>
                  ))}
                </div>
              </CardContent>
            </Card>
          )}
        </div>

        <div className="space-y-4">
          {nextUnit ? (
            <Link href={nextUnit.type === 'quiz' ? `/modules/${moduleId}/quiz?unit=${nextUnit.id}` : `/modules/${moduleId}/lessons/${nextUnit.id}`} className="block">
              <Button className="w-full min-h-11" size="lg">
                <Play className="w-4 h-4 mr-2" />
                {nextUnit.status === 'in-progress' ? t('continueReading') : t('startReading')}
              </Button>
            </Link>
          ) : (
            <Button className="w-full min-h-11" size="lg">
              <CheckCircle className="w-4 h-4 mr-2" />
              {t('takeFinalQuiz')}
            </Button>
          )}

          <div className="space-y-2">
            <Button variant="outline" className="w-full min-h-11">
              <BookOpen className="w-4 h-4 mr-2" />
              {t('viewFlashcards')}
            </Button>
          </div>

          <Card>
            <CardContent className="p-4">
              <div className="text-center">
                <div className="text-2xl font-bold text-teal-600 mb-1">
                  {moduleData.completionPercentage}%
                </div>
                <p className="text-sm text-stone-600">{t('progress')}</p>
                <div className="mt-3 pt-3 border-t border-stone-200">
                  <div className="flex justify-between text-xs text-stone-600">
                    <span>{completedUnits} {t('units').toLowerCase()}</span>
                    <span>{moduleData.estimatedHours}h total</span>
                  </div>
                </div>
              </div>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
