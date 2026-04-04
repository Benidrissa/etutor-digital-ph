'use client';

import { useState, useEffect } from 'react';
import { useTranslations, useLocale } from 'next-intl';
import { useRouter } from '@/i18n/routing';
import {
  AlertDialog,
  AlertDialogContent,
  AlertDialogTitle,
  AlertDialogDescription,
  AlertDialogCancel,
  AlertDialogAction,
} from '@/components/ui/alert-dialog';
import { Button } from '@/components/ui/button';
import { getUserBalance, purchaseCourse, enrollInCourse } from '@/lib/api';
import type { CourseDetailResponse } from '@/lib/api';

interface PurchaseDialogProps {
  course: CourseDetailResponse;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSuccess: () => void;
}

export function PurchaseDialog({ course, open, onOpenChange, onSuccess }: PurchaseDialogProps) {
  const t = useTranslations('Marketplace');
  const tDialog = useTranslations('Marketplace.purchaseDialog');
  const locale = useLocale() as 'en' | 'fr';
  const router = useRouter();

  const [balance, setBalance] = useState<number | null>(null);
  const [purchasing, setPurchasing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const title = locale === 'fr' ? course.title_fr : course.title_en;
  const price = course.price_credits;
  const balanceAfter = balance !== null ? balance - price : null;
  const hasEnoughCredits = balance !== null && balance >= price;

  useEffect(() => {
    if (open && !course.is_free) {
      getUserBalance()
        .then((data) => setBalance(data.balance))
        .catch(() => setBalance(null));
    }
  }, [open, course.is_free]);

  const handleConfirm = async () => {
    setPurchasing(true);
    setError(null);
    try {
      if (course.is_free) {
        await enrollInCourse(course.id);
      } else {
        await purchaseCourse(course.id);
      }
      onOpenChange(false);
      onSuccess();
    } catch {
      setError(tDialog('error'));
    } finally {
      setPurchasing(false);
    }
  };

  const handleBuyCredits = () => {
    onOpenChange(false);
    router.push('/marketplace/credits');
  };

  const needsMoreCredits = !course.is_free && !hasEnoughCredits && balance !== null;

  return (
    <AlertDialog open={open} onOpenChange={(isOpen) => !purchasing && onOpenChange(isOpen)}>
      <AlertDialogContent>
        <AlertDialogTitle>{tDialog('title')}</AlertDialogTitle>
        <AlertDialogDescription>
          {tDialog('description')}
        </AlertDialogDescription>

        <div className="flex flex-col gap-3 mt-1">
          <p className="font-semibold text-stone-900 text-sm">{title}</p>

          {!course.is_free && (
            <div className="rounded-lg bg-stone-50 border border-stone-200 p-3 flex flex-col gap-2 text-sm">
              <div className="flex justify-between items-center">
                <span className="text-stone-500">{tDialog('price')}</span>
                <span className="font-semibold text-stone-900">
                  {t('credits', { count: price })}
                </span>
              </div>
              {balance !== null && (
                <>
                  <div className="flex justify-between items-center">
                    <span className="text-stone-500">{tDialog('currentBalance')}</span>
                    <span className="font-medium text-stone-700">
                      {t('credits', { count: balance })}
                    </span>
                  </div>
                  <div className="border-t border-stone-200 pt-2 flex justify-between items-center">
                    <span className="text-stone-500">{tDialog('balanceAfter')}</span>
                    <span
                      className={`font-semibold ${
                        hasEnoughCredits ? 'text-teal-600' : 'text-red-600'
                      }`}
                    >
                      {hasEnoughCredits
                        ? t('credits', { count: balanceAfter ?? 0 })
                        : tDialog('insufficientCredits')}
                    </span>
                  </div>
                </>
              )}
            </div>
          )}

          {error && (
            <p className="text-sm text-red-600" role="alert">{error}</p>
          )}
        </div>

        <div className="flex flex-col gap-2 sm:flex-row sm:justify-end mt-2">
          <AlertDialogCancel disabled={purchasing}>
            {tDialog('cancel')}
          </AlertDialogCancel>

          {needsMoreCredits ? (
            <Button
              className="min-h-11 bg-amber-500 hover:bg-amber-600 text-white"
              onClick={handleBuyCredits}
            >
              {tDialog('buyCredits')}
            </Button>
          ) : (
            <AlertDialogAction
              className="min-h-11 bg-teal-600 hover:bg-teal-700"
              onClick={handleConfirm}
              disabled={purchasing}
            >
              {purchasing ? tDialog('purchasing') : tDialog('confirm')}
            </AlertDialogAction>
          )}
        </div>
      </AlertDialogContent>
    </AlertDialog>
  );
}
