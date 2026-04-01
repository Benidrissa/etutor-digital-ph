'use client';

import { useEffect, useState } from 'react';
import { useTranslations, useLocale } from 'next-intl';
import { CheckCircle, Circle, Clock, Play, BookOpen, MessageSquare, FileText } from 'lucide-react';
import { Link } from '@/i18n/routing';

import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Progress } from '@/components/ui/progress';
import { getModuleDetailWithProgress, type ModuleDetailWithProgressResponse, type UnitProgressDetail } from '@/lib/api';
import type { Unit } from '@/lib/modules';

interface ModuleProgressOverlayProps {
  moduleId: string;
  staticCompletionPercentage: number;
  staticUnits?: Unit[];
}



function mapStatus(status: string): 'pending' | 'in-progress' | 'completed' {
  if (status === 'in_progress') return 'in-progress';
  if (status === 'completed') return 'completed';
  return 'pending';
}

function getStatusIcon(status: 'pending' | 'in-progress' | 'completed') {
  switch (status) {
    case 'completed':
      return <CheckCircle className="w-5 h-5 text-green-600" />;
    case 'in-progress':
      return <Circle className="w-5 h-5 text-blue-600 fill-blue-100" />;
    default:
      return <Circle className="w-5 h-5 text-stone-400" />;
  }
}

function detectUnitType(unitNumber: string): 'lesson' | 'quiz' | 'case-study' {
  if (unitNumber.toLowerCase().includes('quiz') || unitNumber.toLowerCase().includes('q')) {
    return 'quiz';
  }
  if (unitNumber.toLowerCase().includes('case') || unitNumber.toLowerCase().includes('cs')) {
    return 'case-study';
  }
  return 'lesson';
}

function getTypeIcon(unitNumber: string) {
  const type = detectUnitType(unitNumber);
  switch (type) {
    case 'quiz':
      return <MessageSquare className="w-4 h-4" />;
    case 'case-study':
      return <FileText className="w-4 h-4" />;
    default:
      return <BookOpen className="w-4 h-4" />;
  }
}

function getUnitHref(moduleId: string, unit: UnitProgressDetail): string {
  const type = detectUnitType(unit.unit_number);
  if (type === 'quiz') {
    return `/modules/${moduleId}/quiz?unit=${unit.unit_number}`;
  }
  return `/modules/${moduleId}/lessons/${unit.unit_number}`;
}

export function ModuleProgressOverlay({
  moduleId,
  staticCompletionPercentage,
  staticUnits,
}: ModuleProgressOverlayProps) {
  const t = useTranslations('ModuleOverview');
  const locale = useLocale() as 'en' | 'fr';
  const [data, setData] = useState<ModuleDetailWithProgressResponse | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    getModuleDetailWithProgress(moduleId)
      .then(setData)
      .catch(() => {
        // Silently fall back to static data on error (offline support)
      })
      .finally(() => setLoading(false));
  }, [moduleId]);

  const units = data?.units ?? [];

  if (loading) {
    return (
      <div className="space-y-6 animate-pulse">
        <div className="h-24 bg-stone-100 rounded-lg" />
        <div className="h-48 bg-stone-100 rounded-lg" />
      </div>
    );
  }

  const staticUnitsAsApi: UnitProgressDetail[] = (staticUnits ?? []).map((u, idx) => ({
    id: u.id,
    unit_number: u.id,
    title_fr: u.title.fr,
    title_en: u.title.en,
    description_fr: u.description?.fr,
    description_en: u.description?.en,
    estimated_minutes: u.estimatedMinutes ?? 45,
    order_index: idx,
    status: u.status === 'completed' ? 'completed' : u.status === 'in-progress' ? 'in_progress' : 'pending',
  }));

  const displayUnits = data ? units : staticUnitsAsApi;
  const displayCompletionPct = data ? completionPct : staticCompletionPercentage;
  const displayCompletedCount = displayUnits.filter(u => u.status === 'completed').length;
  const displayTotalCount = displayUnits.length;
  const displayNextUnit = displayUnits.find(u => u.status === 'in_progress' || u.status === 'pending');

  if (!data && displayUnits.length === 0) {
    return null;
  }

  return (
    <div className="space-y-6">
      {/* Progress Card */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center justify-between">
            <span>{t('progress')}</span>
            <span className="text-lg font-bold text-teal-600">
              {t('progressPercent', { percent: Math.round(displayCompletionPct) })}
            </span>
          </CardTitle>
        </CardHeader>
        <CardContent>
          <Progress value={displayCompletionPct} className="mb-4 h-2" />
          <p className="text-sm text-stone-600">
            {t('unitsCompleted', { completed: displayCompletedCount, total: displayTotalCount })}
          </p>
        </CardContent>
      </Card>

      {/* Units List */}
      {displayUnits.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>{t('units')}</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-3">
              {displayUnits.map((unit) => {
                const mappedStatus = mapStatus(unit.status);
                const title = locale === 'fr' ? unit.title_fr : unit.title_en;
                const description = locale === 'fr' ? unit.description_fr : unit.description_en;
                return (
                  <Link
                    key={unit.id}
                    href={getUnitHref(moduleId, unit)}
                    className="block"
                  >
                    <div className="flex items-center gap-4 p-4 border border-stone-200 rounded-lg hover:border-stone-300 hover:bg-stone-50 transition-colors cursor-pointer">
                      <div className="flex items-center gap-3 flex-1">
                        {getStatusIcon(mappedStatus)}
                        <div className="flex items-center gap-2 text-stone-600">
                          {getTypeIcon(unit.unit_number)}
                          <span className="text-sm font-medium">
                            {t('unitNumber', { number: unit.order_index + 1 })}
                          </span>
                        </div>
                        <div className="flex-1">
                          <h4 className="font-medium text-stone-900">{title}</h4>
                          {description && (
                            <p className="text-sm text-stone-600 mt-1">{description}</p>
                          )}
                        </div>
                        <div className="flex items-center gap-2 text-sm text-stone-500">
                          <Clock className="w-4 h-4" />
                          {t('readingTime', { minutes: unit.estimated_minutes })}
                        </div>
                      </div>
                    </div>
                  </Link>
                );
              })}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Sidebar progress summary */}
      <Card>
        <CardContent className="p-4">
          <div className="text-center">
            <div className="text-2xl font-bold text-teal-600 mb-1">
              {Math.round(displayCompletionPct)}%
            </div>
            <p className="text-sm text-stone-600">{t('progress')}</p>
            {data && (
              <div className="mt-3 pt-3 border-t border-stone-200">
                <div className="flex justify-between text-xs text-stone-600">
                  <span>{displayCompletedCount} {t('units').toLowerCase()}</span>
                  <span>{data.estimated_hours}h total</span>
                </div>
              </div>
            )}
          </div>
        </CardContent>
      </Card>

      {/* Continue/Start Button */}
      {displayNextUnit && (
        <Link href={getUnitHref(moduleId, displayNextUnit)} className="block">
          <Button className="w-full min-h-11" size="lg">
            <Play className="w-4 h-4 mr-2" />
            {displayNextUnit.status === 'in_progress' ? t('continueReading') : t('startReading')}
          </Button>
        </Link>
      )}
    </div>
  );
}
