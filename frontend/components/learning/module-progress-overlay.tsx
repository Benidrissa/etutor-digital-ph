'use client';

import { useEffect, useState } from 'react';
import { useTranslations, useLocale } from 'next-intl';
import { CheckCircle, Circle, Clock, Play, BookOpen, MessageSquare, FileText } from 'lucide-react';
import { Link } from '@/i18n/routing';

import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Progress } from '@/components/ui/progress';
import { getModuleDetailWithProgress, getModuleUnits, type ModuleDetailWithProgressResponse, type UnitProgressDetail } from '@/lib/api';
import type { Unit } from '@/lib/modules';

interface ModuleProgressOverlayProps {
  moduleId: string;
  staticCompletionPercentage?: number;
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

function detectUnitType(unit: UnitProgressDetail): 'lesson' | 'quiz' | 'case-study' | 'scenario' {
  if (unit.unit_type) return unit.unit_type;
  const title = (unit.title_fr || unit.title_en || '').toLowerCase();
  if (title.includes('quiz')) return 'quiz';
  if (title.includes('étude de cas') || title.includes('case study')) return 'case-study';
  if (title.includes('scénario') || title.includes('scenario')) return 'scenario';
  return 'lesson';
}

function getTypeIcon(unit: UnitProgressDetail) {
  const type = detectUnitType(unit);
  switch (type) {
    case 'quiz':
      return <MessageSquare className="w-4 h-4" />;
    case 'case-study':
    case 'scenario':
      return <FileText className="w-4 h-4" />;
    default:
      return <BookOpen className="w-4 h-4" />;
  }
}

function getUnitHref(moduleId: string, unit: UnitProgressDetail): string {
  const type = detectUnitType(unit);
  if (type === 'quiz') return `/modules/${moduleId}/quiz?unit=${unit.unit_number}`;
  if (type === 'case-study' || type === 'scenario') return `/modules/${moduleId}/case-study?unit=${unit.unit_number}`;
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
    let cancelled = false;

    async function load() {
      try {
        const result = await getModuleDetailWithProgress(moduleId);
        if (!cancelled) setData(result);
      } catch {
        try {
          const publicResult = await getModuleUnits(moduleId);
          if (!cancelled) {
            setData({
              id: publicResult.module_id,
              module_number: publicResult.module_number,
              level: publicResult.level,
              title_fr: publicResult.title_fr,
              title_en: publicResult.title_en,
              description_fr: publicResult.description_fr,
              description_en: publicResult.description_en,
              estimated_hours: publicResult.estimated_hours,
              prereq_modules: [],
              status: 'locked',
              completion_pct: 0,
              quiz_score_avg: null,
              time_spent_minutes: 0,
              last_accessed: null,
              units: publicResult.units.map((u) => ({
                id: u.id,
                unit_number: u.unit_number,
                title_fr: u.title_fr,
                title_en: u.title_en,
                description_fr: u.description_fr,
                description_en: u.description_en,
                estimated_minutes: u.estimated_minutes,
                order_index: u.order_index,
                unit_type: u.unit_type,
                status: 'pending',
              })),
            });
          }
        } catch {
          // Both endpoints failed — fall back to hardcoded static units
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    load();
    return () => { cancelled = true; };
  }, [moduleId]);

  const staticUnitsFallback: UnitProgressDetail[] = (staticUnits ?? []).map((u, i) => ({
    id: u.id,
    unit_number: u.id,
    title_fr: u.title.fr,
    title_en: u.title.en,
    description_fr: u.description?.fr,
    description_en: u.description?.en,
    estimated_minutes: u.estimatedMinutes,
    order_index: i + 1,
    status: u.status === 'in-progress' ? 'in_progress' : u.status,
  }));

  const completionPct = data ? data.completion_pct : (staticCompletionPercentage ?? 0);
  const units = data ? data.units : staticUnitsFallback;
  const completedCount = units.filter(u => u.status === 'completed').length;
  const totalCount = units.length;
  const nextUnit = units.find(u => u.status === 'in_progress' || u.status === 'pending');

  if (loading) {
    return (
      <div className="space-y-6 animate-pulse">
        <div className="h-24 bg-stone-100 rounded-lg" />
        <div className="h-48 bg-stone-100 rounded-lg" />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Progress Card */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center justify-between">
            <span>{t('progress')}</span>
            <span className="text-lg font-bold text-teal-600">
              {t('progressPercent', { percent: Math.round(completionPct) })}
            </span>
          </CardTitle>
        </CardHeader>
        <CardContent>
          <Progress value={completionPct} className="mb-4 h-2" />
          <p className="text-sm text-stone-600">
            {t('unitsCompleted', { completed: completedCount, total: totalCount })}
          </p>
        </CardContent>
      </Card>

      {/* Units List */}
      {units.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>{t('units')}</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-3">
              {units.map((unit) => {
                const mappedStatus = mapStatus(unit.status);
                const title = locale === 'fr' ? unit.title_fr : unit.title_en;
                const description = locale === 'fr' ? unit.description_fr : unit.description_en;
                return (
                  <Link
                    key={unit.id}
                    href={getUnitHref(moduleId, unit)}
                    className="block"
                  >
                    <div className="p-4 border border-stone-200 rounded-lg hover:border-stone-300 hover:bg-stone-50 transition-colors cursor-pointer">
                      <div className="flex items-start gap-3">
                        <div className="mt-0.5 shrink-0">
                          {getStatusIcon(mappedStatus)}
                        </div>
                        <div className="min-w-0 flex-1">
                          <div className="flex flex-wrap items-center gap-x-2 gap-y-1 mb-1">
                            <div className="flex items-center gap-1 text-stone-600 shrink-0">
                              {getTypeIcon(unit)}
                              <span className="text-sm font-medium">
                                {t('unitNumber', { number: unit.order_index })}
                              </span>
                            </div>
                            <div className="flex items-center gap-1 text-sm text-stone-500 shrink-0">
                              <Clock className="w-4 h-4" />
                              {t('readingTime', { minutes: unit.estimated_minutes })}
                            </div>
                          </div>
                          <h4 className="font-medium text-stone-900">{title}</h4>
                          {description && (
                            <p className="text-sm text-stone-600 mt-1">{description}</p>
                          )}
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
              {Math.round(completionPct)}%
            </div>
            <p className="text-sm text-stone-600">{t('progress')}</p>
            <div className="mt-3 pt-3 border-t border-stone-200">
              <div className="flex justify-between text-xs text-stone-600">
                <span>{completedCount} {t('units').toLowerCase()}</span>
                {data && <span>{data.estimated_hours}h total</span>}
              </div>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Continue/Start Button */}
      {nextUnit && (
        <Link href={getUnitHref(moduleId, nextUnit)} className="block">
          <Button className="w-full min-h-11" size="lg">
            <Play className="w-4 h-4 mr-2" />
            {nextUnit.status === 'in_progress' ? t('continueReading') : t('startReading')}
          </Button>
        </Link>
      )}
    </div>
  );
}
