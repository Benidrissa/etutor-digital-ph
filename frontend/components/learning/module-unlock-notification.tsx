'use client';

import { useTranslations, useLocale } from 'next-intl';
import { useState, useEffect } from 'react';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Unlock, CheckCircle, X, ArrowRight } from 'lucide-react';

interface ModuleUnlockNotificationProps {
  /** Module that was just unlocked */
  unlockedModule: {
    id: string;
    number: number;
    title: {
      en: string;
      fr: string;
    };
    level: number;
  };
  /** Whether the notification is visible */
  isVisible: boolean;
  /** Callback when user dismisses notification */
  onDismiss: () => void;
  /** Callback when user wants to start the module */
  onStartModule: () => void;
  /** Auto-dismiss timeout in ms (optional, defaults to 8000) */
  autoCloseDelay?: number;
}

export function ModuleUnlockNotification({
  unlockedModule,
  isVisible,
  onDismiss,
  onStartModule,
  autoCloseDelay = 8000,
}: ModuleUnlockNotificationProps) {
  const t = useTranslations('ModuleUnlockNotification');
  const locale = useLocale() as 'en' | 'fr';
  const [shouldAutoClose, setShouldAutoClose] = useState(true);

  // Auto-dismiss after delay
  useEffect(() => {
    if (isVisible && shouldAutoClose) {
      const timer = setTimeout(() => {
        onDismiss();
      }, autoCloseDelay);

      return () => clearTimeout(timer);
    }
  }, [isVisible, shouldAutoClose, autoCloseDelay, onDismiss]);

  // Pause auto-close on hover/focus
  const handleMouseEnter = () => setShouldAutoClose(false);
  const handleMouseLeave = () => setShouldAutoClose(true);
  const handleFocus = () => setShouldAutoClose(false);
  const handleBlur = () => setShouldAutoClose(true);

  if (!isVisible) return null;

  return (
    <div
      className="fixed top-4 left-4 right-4 z-50 md:left-auto md:right-4 md:w-96 animate-in slide-in-from-top-4 duration-300"
      onMouseEnter={handleMouseEnter}
      onMouseLeave={handleMouseLeave}
      onFocus={handleFocus}
      onBlur={handleBlur}
    >
      <Card className="bg-gradient-to-r from-teal-50 to-green-50 border-teal-200 shadow-lg">
        <CardContent className="p-4">
          <div className="flex items-start gap-3">
            {/* Icon */}
            <div className="flex h-10 w-10 items-center justify-center rounded-full bg-teal-500 animate-in zoom-in duration-300 delay-200">
              <Unlock className="h-5 w-5 text-white" />
            </div>

            {/* Content */}
            <div className="flex-1 min-w-0">
              <div className="flex items-start justify-between gap-2">
                <div className="space-y-1">
                  <h4 className="text-sm font-semibold text-teal-800">
                    {t('congratulations')}
                  </h4>
                  <p className="text-sm text-teal-700">
                    {t('moduleUnlocked')}
                  </p>
                </div>
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-6 w-6 p-0 text-teal-600 hover:bg-teal-100 rounded-full"
                  onClick={onDismiss}
                  aria-label={t('dismiss')}
                >
                  <X className="h-4 w-4" />
                </Button>
              </div>

              {/* Module Info */}
              <div className="mt-2 p-2 rounded-md bg-white/50 border border-teal-100">
                <div className="flex items-center gap-2">
                  <div className="flex h-6 w-6 items-center justify-center rounded-full bg-teal-500 text-xs font-semibold text-white">
                    {unlockedModule.number}
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium text-teal-800 truncate">
                      {unlockedModule.title[locale]}
                    </p>
                    <p className="text-xs text-teal-600">
                      {t('level')} {unlockedModule.level}
                    </p>
                  </div>
                </div>
              </div>

              {/* Actions */}
              <div className="mt-3 flex gap-2">
                <Button
                  size="sm"
                  className="flex-1 bg-teal-600 hover:bg-teal-700 text-white min-h-11"
                  onClick={onStartModule}
                >
                  {t('startNow')}
                  <ArrowRight className="ml-1 h-3 w-3" />
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  className="border-teal-200 text-teal-700 hover:bg-teal-50 min-h-11"
                  onClick={onDismiss}
                >
                  {t('later')}
                </Button>
              </div>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

/**
 * Success notification variant for when prerequisites are met
 */
interface PrerequisiteSuccessNotificationProps {
  /** Module that can now be unlocked */
  eligibleModule: {
    id: string;
    number: number;
    title: {
      en: string;
      fr: string;
    };
  };
  /** Achievement that triggered this (e.g., "80% quiz score", "Module completion") */
  achievement: string;
  /** Whether the notification is visible */
  isVisible: boolean;
  /** Callback when user dismisses notification */
  onDismiss: () => void;
  /** Callback when user wants to unlock the module */
  onUnlockModule: () => void;
}

export function PrerequisiteSuccessNotification({
  eligibleModule,
  achievement,
  isVisible,
  onDismiss,
  onUnlockModule,
}: PrerequisiteSuccessNotificationProps) {
  const t = useTranslations('PrerequisiteSuccessNotification');
  const locale = useLocale() as 'en' | 'fr';

  if (!isVisible) return null;

  return (
    <div className="fixed top-4 left-4 right-4 z-50 md:left-auto md:right-4 md:w-96 animate-in slide-in-from-right-4 duration-300">
      <Alert className="bg-green-50 border-green-200">
        <CheckCircle className="h-4 w-4 text-green-600" />
        <AlertDescription className="space-y-3">
          <div className="flex items-start justify-between">
            <div>
              <p className="text-sm font-medium text-green-800">
                {achievement}
              </p>
              <p className="text-xs text-green-600 mt-1">
                {t('readyToUnlock')} {eligibleModule.title[locale]}
              </p>
            </div>
            <Button
              variant="ghost"
              size="sm"
              className="h-6 w-6 p-0 text-green-600 hover:bg-green-100 rounded-full"
              onClick={onDismiss}
              aria-label={t('dismiss')}
            >
              <X className="h-4 w-4" />
            </Button>
          </div>

          <div className="flex gap-2">
            <Button
              size="sm"
              className="bg-green-600 hover:bg-green-700 text-white min-h-11"
              onClick={onUnlockModule}
            >
              {t('unlockNow')}
            </Button>
            <Button
              variant="outline"
              size="sm"
              className="border-green-200 text-green-700 hover:bg-green-50 min-h-11"
              onClick={onDismiss}
            >
              {t('later')}
            </Button>
          </div>
        </AlertDescription>
      </Alert>
    </div>
  );
}