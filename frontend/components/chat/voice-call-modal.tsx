'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { useLocale, useTranslations } from 'next-intl';
import { Phone, PhoneOff, Mic, MicOff, Loader2, X } from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
  startVoiceSession,
  closeVoiceSession,
} from '@/lib/tutor-voice-api';
import {
  connectRealtime,
  type RealtimeConnection,
} from '@/lib/realtime-client';
import { cn } from '@/lib/utils';

interface VoiceCallModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

type CallState =
  | 'idle'
  | 'requesting_token'
  | 'connecting'
  | 'in_call'
  | 'ending'
  | 'ended'
  | 'cap_reached'
  | 'mic_denied'
  | 'failed';

function formatDuration(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${s.toString().padStart(2, '0')}`;
}

export function VoiceCallModal({ open, onOpenChange }: VoiceCallModalProps) {
  const t = useTranslations('ChatTutor.voice');
  const locale = useLocale();
  const language = (locale === 'fr' ? 'fr' : 'en') as 'fr' | 'en';

  const [state, setState] = useState<CallState>('idle');
  const [minutesUsed, setMinutesUsed] = useState<number | null>(null);
  const [minutesCap, setMinutesCap] = useState<number | null>(null);
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const [muted, setMuted] = useState(false);

  const connectionRef = useRef<RealtimeConnection | null>(null);
  const sessionIdRef = useRef<string | null>(null);
  const startedAtRef = useRef<number | null>(null);

  const hangUp = useCallback(async () => {
    const conn = connectionRef.current;
    const sessionId = sessionIdRef.current;
    const startedAt = startedAtRef.current;

    setState('ending');
    if (conn) conn.close();
    connectionRef.current = null;

    if (sessionId && startedAt) {
      const duration = Math.max(0, Math.floor((Date.now() - startedAt) / 1000));
      const { data } = await closeVoiceSession(sessionId, duration);
      if (data) {
        setMinutesUsed(data.minutes_used_today);
        setMinutesCap(data.minutes_cap_per_day);
      }
    }
    sessionIdRef.current = null;
    startedAtRef.current = null;
    setState('ended');
  }, []);

  const startCall = useCallback(async () => {
    setState('requesting_token');
    const { data, status } = await startVoiceSession(language);
    if (!data) {
      setState(status === 403 ? 'cap_reached' : 'failed');
      return;
    }
    setMinutesUsed(data.minutes_used_today);
    setMinutesCap(data.minutes_cap_per_day);
    sessionIdRef.current = data.session_id;

    setState('connecting');
    try {
      const conn = await connectRealtime({
        clientSecret: data.client_secret,
        model: data.model,
        onError: () => {
          void hangUp();
        },
      });
      connectionRef.current = conn;
      startedAtRef.current = Date.now();
      setElapsedSeconds(0);
      setState('in_call');
    } catch (err) {
      if ((err as Error).name === 'NotAllowedError') {
        setState('mic_denied');
      } else {
        setState('failed');
      }
    }
  }, [language, hangUp]);

  const toggleMute = useCallback(() => {
    const conn = connectionRef.current;
    if (!conn) return;
    const nextMuted = !muted;
    conn.micStream.getAudioTracks().forEach((track) => {
      track.enabled = !nextMuted;
    });
    setMuted(nextMuted);
  }, [muted]);

  // Elapsed-second ticker; auto-hang-up when we'd exceed the daily cap.
  useEffect(() => {
    if (state !== 'in_call' || !startedAtRef.current) return;
    const id = window.setInterval(() => {
      const startedAt = startedAtRef.current;
      if (!startedAt) return;
      const elapsed = Math.floor((Date.now() - startedAt) / 1000);
      setElapsedSeconds(elapsed);
      if (minutesCap !== null && minutesUsed !== null) {
        const remainingMinutes = Math.max(0, minutesCap - minutesUsed);
        if (elapsed >= remainingMinutes * 60) {
          void hangUp();
        }
      }
    }, 1000);
    return () => window.clearInterval(id);
  }, [state, minutesCap, minutesUsed, hangUp]);

  // Tear down when the modal closes so the mic light doesn't stay on.
  useEffect(() => {
    if (!open && state !== 'idle') {
      const conn = connectionRef.current;
      if (conn) conn.close();
      connectionRef.current = null;
      if (sessionIdRef.current && startedAtRef.current) {
        const duration = Math.max(
          0,
          Math.floor((Date.now() - startedAtRef.current) / 1000),
        );
        void closeVoiceSession(sessionIdRef.current, duration);
      }
      sessionIdRef.current = null;
      startedAtRef.current = null;
      setState('idle');
      setMuted(false);
      setElapsedSeconds(0);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  if (!open) return null;

  const statusLine = (() => {
    switch (state) {
      case 'idle':
      case 'ended':
        return t('callReady');
      case 'requesting_token':
      case 'connecting':
        return t('connecting');
      case 'in_call':
        return t('inCall');
      case 'ending':
        return t('ending');
      case 'cap_reached':
        return t('capReached', { cap: minutesCap ?? 10 });
      case 'mic_denied':
        return t('micDenied');
      case 'failed':
        return t('callFailed');
    }
  })();

  const showStart =
    state === 'idle' ||
    state === 'ended' ||
    state === 'cap_reached' ||
    state === 'mic_denied' ||
    state === 'failed';
  const startDisabled = state === 'cap_reached';

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="voice-call-title"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
      onClick={() => onOpenChange(false)}
    >
      <div
        className={cn(
          'w-full max-w-md rounded-lg bg-background p-6 shadow-lg',
          'flex flex-col gap-4',
        )}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between">
          <h2 id="voice-call-title" className="text-lg font-semibold">
            {t('callTitle')}
          </h2>
          <Button
            variant="ghost"
            size="icon"
            onClick={() => onOpenChange(false)}
            aria-label={t('close')}
            className="h-8 w-8"
          >
            <X className="h-4 w-4" />
          </Button>
        </div>

        <div className="flex flex-col items-center gap-4 py-4">
          <div className="text-sm text-muted-foreground text-center">
            {statusLine}
          </div>

          {state === 'in_call' && (
            <div className="text-3xl font-semibold tabular-nums">
              {formatDuration(elapsedSeconds)}
            </div>
          )}

          {minutesUsed !== null && minutesCap !== null && (
            <div className="text-xs text-muted-foreground">
              {t('minutesRemaining', {
                remaining: Math.max(0, minutesCap - minutesUsed),
                cap: minutesCap,
              })}
            </div>
          )}

          <div className="flex items-center gap-3">
            {state === 'in_call' && (
              <Button
                variant={muted ? 'default' : 'outline'}
                size="icon"
                onClick={toggleMute}
                className="h-12 w-12 rounded-full"
                aria-label={muted ? t('unmute') : t('mute')}
              >
                {muted ? (
                  <MicOff className="h-5 w-5" />
                ) : (
                  <Mic className="h-5 w-5" />
                )}
              </Button>
            )}

            {showStart ? (
              <Button
                onClick={startCall}
                disabled={startDisabled}
                className="h-12 min-w-32 gap-2"
              >
                <Phone className="h-4 w-4" />
                {t('startCall')}
              </Button>
            ) : state === 'requesting_token' || state === 'connecting' ? (
              <Button disabled className="h-12 min-w-32 gap-2">
                <Loader2 className="h-4 w-4 animate-spin" />
                {t('connecting')}
              </Button>
            ) : state === 'in_call' || state === 'ending' ? (
              <Button
                variant="destructive"
                onClick={hangUp}
                disabled={state === 'ending'}
                className="h-12 min-w-32 gap-2"
              >
                <PhoneOff className="h-4 w-4" />
                {t('hangUp')}
              </Button>
            ) : null}
          </div>
        </div>
      </div>
    </div>
  );
}
