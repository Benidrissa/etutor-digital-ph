'use client';

import { useState, useEffect } from 'react';
import { useTranslations } from 'next-intl';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { X } from 'lucide-react';

interface BeforeInstallPromptEvent extends Event {
  prompt(): Promise<void>;
  userChoice: Promise<{
    outcome: 'accepted' | 'dismissed';
  }>;
}

export function InstallPrompt() {
  const t = useTranslations('PWA');
  const [deferredPrompt, setDeferredPrompt] = useState<BeforeInstallPromptEvent | null>(null);
  const [showInstallPrompt, setShowInstallPrompt] = useState(false);

  useEffect(() => {
    // Track visit count
    const visitCount = parseInt(localStorage.getItem('pwa-visit-count') || '0', 10);
    const newVisitCount = visitCount + 1;
    localStorage.setItem('pwa-visit-count', newVisitCount.toString());

    // Check if user has already dismissed the prompt
    const hasUserDismissed = localStorage.getItem('pwa-install-dismissed') === 'true';
    const shouldShow = newVisitCount >= 2 && !hasUserDismissed;
    
    // Listen for beforeinstallprompt event
    const handleBeforeInstallPrompt = (e: Event) => {
      e.preventDefault();
      setDeferredPrompt(e as BeforeInstallPromptEvent);
      
      // Only show prompt if conditions are met
      if (shouldShow) {
        // Use setTimeout to avoid setState in effect
        setTimeout(() => setShowInstallPrompt(true), 0);
      }
    };

    window.addEventListener('beforeinstallprompt', handleBeforeInstallPrompt);

    return () => {
      window.removeEventListener('beforeinstallprompt', handleBeforeInstallPrompt);
    };
  }, []);

  const handleInstallClick = async () => {
    if (!deferredPrompt) return;

    // Show the install prompt
    await deferredPrompt.prompt();

    // Wait for user choice
    const { outcome } = await deferredPrompt.userChoice;
    
    if (outcome === 'accepted') {
      console.log('User accepted the install prompt');
    } else {
      console.log('User dismissed the install prompt');
    }

    // Clear the deferred prompt
    setDeferredPrompt(null);
    setShowInstallPrompt(false);
  };

  const handleDismiss = () => {
    localStorage.setItem('pwa-install-dismissed', 'true');
    setShowInstallPrompt(false);
  };

  // Don't show if no deferred prompt or if user shouldn't see it
  if (!showInstallPrompt || !deferredPrompt) {
    return null;
  }

  return (
    <div className="fixed bottom-4 left-4 right-4 z-50 md:left-auto md:right-4 md:w-80">
      <Card className="border-green-200 bg-green-50 shadow-lg">
        <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
          <CardTitle className="text-sm font-medium text-green-900">
            {t('installTitle')}
          </CardTitle>
          <Button
            variant="ghost"
            size="sm"
            onClick={handleDismiss}
            className="h-6 w-6 p-0 text-green-700 hover:bg-green-100"
          >
            <X className="h-4 w-4" />
          </Button>
        </CardHeader>
        <CardContent className="pt-2">
          <p className="text-sm text-green-800 mb-3">
            {t('installDescription')}
          </p>
          <div className="flex gap-2">
            <Button
              onClick={handleInstallClick}
              className="flex-1 bg-green-600 hover:bg-green-700 text-white"
              size="sm"
            >
              {t('install')}
            </Button>
            <Button
              onClick={handleDismiss}
              variant="outline"
              className="border-green-300 text-green-700 hover:bg-green-100"
              size="sm"
            >
              {t('later')}
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}