'use client';

import { useState, useEffect, useRef, useCallback } from 'react';
import { useTranslations } from 'next-intl';
import { useSearchParams, usePathname } from 'next/navigation';
import { useRouter } from '@/i18n/routing';
import Image from 'next/image';
import { QrCode, Keyboard, CheckCircle, AlertCircle, Loader2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import {
  previewActivationCode,
  redeemActivationCode,
  ApiError,
  type ActivationPreviewResponse,
} from '@/lib/api';

type Mode = 'code' | 'qr';
type Status = 'idle' | 'checking' | 'preview' | 'activating' | 'success' | 'error';

function CoursePreviewCard({
  preview,
  locale,
  onActivate,
  activating,
  t,
}: {
  preview: ActivationPreviewResponse;
  locale: string;
  onActivate: () => void;
  activating: boolean;
  t: ReturnType<typeof useTranslations>;
}) {
  const title = locale === 'fr' ? preview.title_fr : preview.title_en;
  const description = locale === 'fr' ? preview.description_fr : preview.description_en;

  return (
    <Card className="w-full border-teal-200 bg-teal-50/30">
      <CardHeader className="pb-3">
        <p className="text-xs font-medium text-teal-600 uppercase tracking-wide">
          {t('coursePreview')}
        </p>
        {preview.cover_image_url && (
          <div className="relative w-full h-36 rounded-lg overflow-hidden mt-2">
            <Image
              src={preview.cover_image_url}
              alt={title}
              fill
              className="object-cover"
              sizes="(max-width: 640px) 100vw, 480px"
            />
          </div>
        )}
        <CardTitle className="text-lg leading-tight mt-2">{title}</CardTitle>
        {preview.expert_name && (
          <CardDescription className="text-sm text-stone-500">
            {t('expertName', { name: preview.expert_name })}
          </CardDescription>
        )}
      </CardHeader>
      {description && (
        <CardContent className="pt-0 pb-4">
          <p className="text-sm text-stone-600 line-clamp-3">{description}</p>
        </CardContent>
      )}
      <CardContent className="pt-0">
        <Button
          onClick={onActivate}
          disabled={activating}
          className="w-full min-h-11 bg-teal-600 hover:bg-teal-700 text-white"
        >
          {activating ? (
            <>
              <Loader2 className="h-4 w-4 mr-2 animate-spin" />
              {t('activating')}
            </>
          ) : (
            t('activate')
          )}
        </Button>
      </CardContent>
    </Card>
  );
}

function QrScanner({
  onScan,
  onError,
  t,
}: {
  onScan: (code: string) => void;
  onError: () => void;
  t: ReturnType<typeof useTranslations>;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const scannerRef = useRef<unknown>(null);
  const [cameraError, setCameraError] = useState(false);

  useEffect(() => {
    let mounted = true;

    async function startScanner() {
      try {
        const { Html5Qrcode } = await import('html5-qrcode');
        if (!containerRef.current || !mounted) return;

        const scanner = new Html5Qrcode('qr-reader');
        scannerRef.current = scanner;

        await scanner.start(
          { facingMode: 'environment' },
          { fps: 10, qrbox: { width: 250, height: 250 } },
          (decodedText: string) => {
            const url = new URL(decodedText);
            const code = url.searchParams.get('code') || decodedText;
            onScan(code);
          },
          () => {}
        );
      } catch {
        if (mounted) {
          setCameraError(true);
          onError();
        }
      }
    }

    startScanner();

    return () => {
      mounted = false;
      if (scannerRef.current) {
        const scanner = scannerRef.current as { stop: () => Promise<void> };
        scanner.stop().catch(() => {});
      }
    };
  }, [onScan, onError]);

  if (cameraError) {
    return (
      <div className="flex flex-col items-center gap-3 py-6 text-center">
        <AlertCircle className="h-10 w-10 text-red-500" />
        <p className="text-sm text-stone-600">{t('cameraError')}</p>
      </div>
    );
  }

  return (
    <div className="flex flex-col items-center gap-3">
      <p className="text-sm text-stone-500">{t('scanInstructions')}</p>
      <div
        id="qr-reader"
        ref={containerRef}
        className="w-full max-w-xs rounded-lg overflow-hidden border border-stone-200"
      />
    </div>
  );
}

export default function ActivatePage() {
  const t = useTranslations('ActivationCodes');
  const searchParams = useSearchParams();
  const pathname = usePathname();
  const router = useRouter();
  const locale = pathname.split('/')[1] || 'fr';

  const [mode, setMode] = useState<Mode>('code');
  const [code, setCode] = useState('');
  const [status, setStatus] = useState<Status>('idle');
  const [preview, setPreview] = useState<ActivationPreviewResponse | null>(null);
  const [errorMessage, setErrorMessage] = useState('');
  const [redeemMethod, setRedeemMethod] = useState<'code' | 'qr'>('code');

  const urlCode = searchParams.get('code');

  const doCheck = async (codeToCheck: string, method: 'code' | 'qr' = 'code') => {
    const trimmed = codeToCheck.trim();
    if (!trimmed) {
      setErrorMessage(t('codeRequired'));
      return;
    }
    setStatus('checking');
    setErrorMessage('');
    setPreview(null);
    setRedeemMethod(method);
    try {
      const data = await previewActivationCode(trimmed);
      setPreview(data);
      setCode(trimmed);
      setStatus('preview');
      if (mode === 'qr') setMode('code');
    } catch (err) {
      let msg = t('invalidCode');
      if (err instanceof ApiError) {
        if (err.code === 'already_enrolled') msg = t('alreadyEnrolled');
        else if (err.code === 'exhausted') msg = t('exhaustedCode');
      }
      setErrorMessage(msg);
      setStatus('error');
    }
  };

  const handleCheck = (codeToCheck: string, method: 'code' | 'qr' = 'code') => {
    void doCheck(codeToCheck, method);
  };

  const initializedRef = useRef(false);

  useEffect(() => {
    if (!urlCode || initializedRef.current) return;
    initializedRef.current = true;
    const timer = setTimeout(() => {
      void doCheck(urlCode, 'code');
    }, 0);
    return () => clearTimeout(timer);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [urlCode]);

  const handleActivate = async () => {
    if (!preview) return;
    setStatus('activating');
    try {
      const result = await redeemActivationCode(code, redeemMethod);
      setStatus('success');
      setTimeout(() => {
        router.push(`/courses/${result.course_slug}`);
      }, 1500);
    } catch (err) {
      let msg = t('error');
      if (err instanceof ApiError) {
        if (err.code === 'already_enrolled') msg = t('alreadyEnrolled');
        else if (err.code === 'exhausted') msg = t('exhaustedCode');
      }
      setErrorMessage(msg);
      setStatus('error');
    }
  };

  const handleQrScan = useCallback(
    (scannedCode: string) => {
      setCode(scannedCode);
      handleCheck(scannedCode, 'qr');
    },
    [handleCheck]
  );

  const handleQrError = useCallback(() => {
    setMode('code');
  }, []);

  const handleReset = () => {
    setStatus('idle');
    setPreview(null);
    setErrorMessage('');
    setCode('');
    setRedeemMethod('code');
  };

  return (
    <div className="min-h-screen flex items-start justify-center px-4 py-8 md:py-16">
      <div className="w-full max-w-md space-y-6">
        <div className="text-center">
          <h1 className="text-2xl font-bold text-stone-900">{t('title')}</h1>
        </div>

        {status !== 'success' && (
          <div className="flex gap-2 rounded-lg border border-stone-200 p-1 bg-stone-50">
            <button
              type="button"
              onClick={() => { setMode('code'); handleReset(); }}
              className={`flex-1 flex items-center justify-center gap-2 rounded-md py-2 text-sm font-medium transition-colors min-h-11 ${
                mode === 'code'
                  ? 'bg-white text-teal-700 shadow-sm border border-stone-200'
                  : 'text-stone-500 hover:text-stone-700'
              }`}
            >
              <Keyboard className="h-4 w-4" />
              {t('enterCode')}
            </button>
            <button
              type="button"
              onClick={() => { setMode('qr'); handleReset(); }}
              className={`flex-1 flex items-center justify-center gap-2 rounded-md py-2 text-sm font-medium transition-colors min-h-11 ${
                mode === 'qr'
                  ? 'bg-white text-teal-700 shadow-sm border border-stone-200'
                  : 'text-stone-500 hover:text-stone-700'
              }`}
            >
              <QrCode className="h-4 w-4" />
              {t('scanQr')}
            </button>
          </div>
        )}

        {mode === 'code' && status !== 'success' && (
          <div className="space-y-3">
            <div className="flex gap-2">
              <Input
                type="text"
                value={code}
                onChange={(e) => {
                  setCode(e.target.value);
                  if (status === 'error') setStatus('idle');
                  if (status === 'preview') {
                    setStatus('idle');
                    setPreview(null);
                  }
                }}
                placeholder={t('codePlaceholder')}
                className="flex-1 min-h-11 text-base uppercase"
                aria-label={t('enterCode')}
                disabled={status === 'checking' || status === 'activating'}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && status !== 'preview') {
                    handleCheck(code);
                  }
                }}
              />
              {status !== 'preview' && (
                <Button
                  onClick={() => handleCheck(code)}
                  disabled={status === 'checking' || !code.trim()}
                  className="min-h-11 bg-teal-600 hover:bg-teal-700 text-white"
                >
                  {status === 'checking' ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    t('check')
                  )}
                </Button>
              )}
            </div>

            {(status === 'error' || errorMessage) && (
              <div
                role="alert"
                className="flex items-center gap-2 rounded-lg bg-red-50 border border-red-200 px-3 py-2 text-sm text-red-700"
              >
                <AlertCircle className="h-4 w-4 shrink-0" />
                {errorMessage}
              </div>
            )}
          </div>
        )}

        {mode === 'qr' && status !== 'preview' && status !== 'activating' && status !== 'success' && (
          <QrScanner onScan={handleQrScan} onError={handleQrError} t={t} />
        )}

        {(status === 'preview' || status === 'activating') && preview && (
          <CoursePreviewCard
            preview={preview}
            locale={locale}
            onActivate={handleActivate}
            activating={status === 'activating'}
            t={t}
          />
        )}

        {status === 'success' && (
          <div className="flex flex-col items-center gap-4 py-8 text-center">
            <div className="rounded-full bg-green-100 p-4">
              <CheckCircle className="h-10 w-10 text-green-600" />
            </div>
            <div>
              <p className="text-lg font-semibold text-stone-900">{t('success')}</p>
              <p className="text-sm text-stone-500 mt-1">{t('redirecting')}</p>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
