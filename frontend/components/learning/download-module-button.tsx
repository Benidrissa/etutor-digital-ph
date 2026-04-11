'use client';

import { useState } from 'react';
import { useTranslations } from 'next-intl';
import {
  Download,
  CheckCircle,
  Trash2,
  XCircle,
  Loader2,
  Wifi,
  AlertTriangle,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Progress } from '@/components/ui/progress';
import { Checkbox } from '@/components/ui/checkbox';
import { Label } from '@/components/ui/label';
import { useDownloadManager } from '@/lib/hooks/use-download-manager';
import { formatBytes } from '@/lib/offline/download-manager';

interface DownloadModuleButtonProps {
  moduleId: string;
  locale: 'fr' | 'en';
  unitCount: number;
  level?: number;
  country?: string;
}

export function DownloadModuleButton({
  moduleId,
  locale,
  unitCount,
  level = 1,
  country = 'CI',
}: DownloadModuleButtonProps) {
  const t = useTranslations('Offline');
  const [wifiOnly, setWifiOnly] = useState(true);
  const [showConfirm, setShowConfirm] = useState(false);

  const {
    status,
    progress,
    isDownloading,
    isAvailableOffline,
    canDownload,
    estimatedSize,
    downloadedUnits,
    totalUnits,
    error,
    download,
    cancel,
    remove,
  } = useDownloadManager(moduleId, locale, unitCount);

  const progressPct =
    totalUnits > 0 ? Math.round((downloadedUnits / totalUnits) * 100) : 0;

  const handleDownload = async () => {
    setShowConfirm(false);
    await download({ wifiOnly, level, country });
  };

  // Available offline — show status + delete button
  if (isAvailableOffline) {
    return (
      <div className="rounded-lg border border-teal-200 bg-teal-50 p-4 space-y-3">
        <div className="flex items-center gap-2 text-teal-700">
          <CheckCircle className="w-5 h-5 shrink-0" />
          <span className="text-sm font-medium">{t('availableOffline')}</span>
        </div>
        <Button
          variant="outline"
          size="sm"
          className="w-full text-red-600 border-red-200 hover:bg-red-50 min-h-11"
          onClick={remove}
        >
          <Trash2 className="w-4 h-4 mr-2" />
          {t('removeDownload')}
        </Button>
      </div>
    );
  }

  // Currently downloading — show progress
  if (isDownloading) {
    return (
      <div className="rounded-lg border border-amber-200 bg-amber-50 p-4 space-y-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2 text-amber-700">
            <Loader2 className="w-4 h-4 animate-spin" />
            <span className="text-sm font-medium">{t('downloading')}</span>
          </div>
          <span className="text-xs text-amber-600">
            {downloadedUnits}/{totalUnits} {t('units')}
          </span>
        </div>

        <div className="space-y-1">
          <div className="flex justify-between text-xs text-amber-600">
            <span>{t('downloadProgress')}</span>
            <span>{progressPct}%</span>
          </div>
          <Progress value={progressPct} />
        </div>

        {progress?.currentUnit && (
          <p className="text-xs text-amber-600">
            {progress.currentContentType === 'lesson' && t('downloadingLesson')}
            {progress.currentContentType === 'quiz' && t('downloadingQuiz')}
            {progress.currentContentType === 'case_study' && t('downloadingCaseStudy')}
            {' '}{progress.currentUnit}
          </p>
        )}

        <Button
          variant="outline"
          size="sm"
          className="w-full min-h-11"
          onClick={cancel}
        >
          <XCircle className="w-4 h-4 mr-2" />
          {t('cancel')}
        </Button>
      </div>
    );
  }

  // Error state — show error + retry
  if (status === 'error') {
    return (
      <div className="rounded-lg border border-red-200 bg-red-50 p-4 space-y-3">
        <div className="flex items-center gap-2 text-red-700">
          <AlertTriangle className="w-5 h-5 shrink-0" />
          <span className="text-sm font-medium">{error || t('downloadFailed')}</span>
        </div>
        {downloadedUnits > 0 && (
          <p className="text-xs text-red-600">
            {t('partialDownload', { count: downloadedUnits, total: totalUnits })}
          </p>
        )}
        <div className="flex gap-2">
          <Button
            size="sm"
            className="flex-1 min-h-11"
            onClick={handleDownload}
          >
            {t('retry')}
          </Button>
          {downloadedUnits > 0 && (
            <Button
              variant="outline"
              size="sm"
              className="min-h-11 text-red-600 border-red-200"
              onClick={remove}
            >
              <Trash2 className="w-4 h-4" />
            </Button>
          )}
        </div>
      </div>
    );
  }

  // Not downloaded — show download button or limit warning
  if (!canDownload) {
    return (
      <div className="rounded-lg border border-stone-200 bg-stone-50 p-4 space-y-2">
        <div className="flex items-center gap-2 text-stone-500">
          <AlertTriangle className="w-4 h-4" />
          <span className="text-sm">{t('moduleLimitReached')}</span>
        </div>
        <p className="text-xs text-stone-400">{t('moduleLimitHint')}</p>
      </div>
    );
  }

  // Show confirm dialog
  if (showConfirm) {
    return (
      <div className="rounded-lg border border-stone-200 bg-white p-4 space-y-3">
        <p className="text-sm text-stone-700">
          {t('downloadConfirm', { size: formatBytes(estimatedSize) })}
        </p>

        <div className="flex items-center gap-2">
          <Checkbox
            id="wifi-only"
            checked={wifiOnly}
            onCheckedChange={(checked) => setWifiOnly(checked === true)}
          />
          <Label htmlFor="wifi-only" className="text-sm text-stone-600 flex items-center gap-1">
            <Wifi className="w-3.5 h-3.5" />
            {t('wifiOnly')}
          </Label>
        </div>

        <div className="flex gap-2">
          <Button
            size="sm"
            className="flex-1 min-h-11 bg-teal-600 hover:bg-teal-700"
            onClick={handleDownload}
          >
            <Download className="w-4 h-4 mr-2" />
            {t('startDownload')}
          </Button>
          <Button
            variant="outline"
            size="sm"
            className="min-h-11"
            onClick={() => setShowConfirm(false)}
          >
            {t('cancelAction')}
          </Button>
        </div>
      </div>
    );
  }

  // Default: download button
  return (
    <Button
      variant="outline"
      className="w-full min-h-11"
      onClick={() => setShowConfirm(true)}
    >
      <Download className="w-4 h-4 mr-2" />
      {t('downloadForOffline')}
      <span className="ml-auto text-xs text-stone-400">
        ~{formatBytes(estimatedSize)}
      </span>
    </Button>
  );
}
