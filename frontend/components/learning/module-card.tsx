'use client';

import { useTranslations, useLocale } from 'next-intl';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Lock, CheckCircle, PlayCircle } from 'lucide-react';
import type { Module } from '@/lib/modules';

interface ModuleCardProps {
  module: Module;
  isUnlocked: boolean;
  onClick: () => void;
}

export function ModuleCard({ module, isUnlocked, onClick }: ModuleCardProps) {
  const t = useTranslations('ModuleCard');
  const locale = useLocale() as 'en' | 'fr';
  
  const getStatusIcon = () => {
    if (!isUnlocked || module.status === 'locked') {
      return <Lock className="h-4 w-4 text-stone-400" />;
    }
    if (module.status === 'completed') {
      return <CheckCircle className="h-4 w-4 text-green-600" />;
    }
    return <PlayCircle className="h-4 w-4 text-teal-600" />;
  };

  const getStatusColor = () => {
    if (!isUnlocked || module.status === 'locked') {
      return 'bg-stone-50 border-stone-200 opacity-60';
    }
    if (module.status === 'completed') {
      return 'bg-green-50 border-green-200 shadow-sm';
    }
    if (module.status === 'unlocked') {
      return 'bg-teal-50 border-teal-200 shadow-sm animate-in fade-in duration-500';
    }
    return 'bg-teal-50 border-teal-200';
  };

  const getProgressText = () => {
    if (!isUnlocked || module.status === 'locked') {
      return t('locked');
    }
    if (module.status === 'completed') {
      return t('completed');
    }
    return t('progress', { percent: module.completionPercentage });
  };

  return (
    <Card 
      className={`relative cursor-pointer transition-all duration-200 hover:shadow-md ${getStatusColor()}`}
      onClick={isUnlocked ? onClick : undefined}
    >
      <CardHeader className="pb-3">
        <div className="flex items-start justify-between">
          <div className="flex items-center gap-2">
            <div className="flex h-8 w-8 items-center justify-center rounded-full bg-white text-sm font-semibold text-teal-700">
              {module.number}
            </div>
            {getStatusIcon()}
          </div>
          <div className="text-xs text-stone-500">
            {t('hours', { count: module.estimatedHours })}
          </div>
        </div>
        <CardTitle className="text-base leading-tight">
          {module.title[locale]}
        </CardTitle>
      </CardHeader>
      <CardContent className="pt-0">
        <div className="space-y-3">
          {/* Progress Bar */}
          {(isUnlocked && module.status !== 'locked') && (
            <div className="space-y-1">
              <div className="h-2 rounded-full bg-stone-200">
                <div 
                  className={`h-2 rounded-full transition-all duration-500 ${
                    module.status === 'completed' 
                      ? 'bg-green-500' 
                      : 'bg-teal-500'
                  }`}
                  style={{ width: `${module.completionPercentage}%` }}
                />
              </div>
              <p className="text-xs text-stone-600">
                {getProgressText()}
              </p>
            </div>
          )}
          
          {/* Status Text for Locked Modules */}
          {(!isUnlocked || module.status === 'locked') && (
            <p className="text-xs text-stone-500">
              {t('prerequisitesRequired')}
            </p>
          )}
          
          {/* Action Button */}
          <Button 
            variant={module.status === 'completed' ? 'secondary' : 'default'}
            size="sm"
            className="w-full min-h-11"
            disabled={!isUnlocked || module.status === 'locked'}
          >
            {module.status === 'completed' 
              ? t('review')
              : module.status === 'in-progress'
              ? t('continue') 
              : t('start')
            }
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}