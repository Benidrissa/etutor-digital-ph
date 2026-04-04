'use client';

import { useEffect, useRef, useState } from 'react';
import { useTranslations } from 'next-intl';
import {
  Download,
  Pause,
  Play,
  Volume2,
  VolumeX,
} from 'lucide-react';

import { API_BASE } from '@/lib/api';

interface ModuleAudioPlayerProps {
  mediaId: string;
  moduleId: string;
  language: 'fr' | 'en';
  durationSeconds?: number;
}

export function ModuleAudioPlayer({
  mediaId,
  moduleId,
  language,
  durationSeconds,
}: ModuleAudioPlayerProps) {
  const t = useTranslations('ModuleMedia');
  const audioRef = useRef<HTMLAudioElement>(null);
  const [isPlaying, setIsPlaying] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(durationSeconds ?? 0);
  const [isMuted, setIsMuted] = useState(false);
  const [volume, setVolume] = useState(1);

  const audioUrl = `${API_BASE}/api/v1/modules/${moduleId}/media/${mediaId}/data`;
  const downloadUrl = audioUrl;

  useEffect(() => {
    const audio = audioRef.current;
    if (!audio) return;

    const onTimeUpdate = () => setCurrentTime(audio.currentTime);
    const onDurationChange = () => setDuration(audio.duration || 0);
    const onEnded = () => setIsPlaying(false);

    audio.addEventListener('timeupdate', onTimeUpdate);
    audio.addEventListener('durationchange', onDurationChange);
    audio.addEventListener('ended', onEnded);

    return () => {
      audio.removeEventListener('timeupdate', onTimeUpdate);
      audio.removeEventListener('durationchange', onDurationChange);
      audio.removeEventListener('ended', onEnded);
    };
  }, []);

  const togglePlay = async () => {
    const audio = audioRef.current;
    if (!audio) return;
    if (isPlaying) {
      audio.pause();
      setIsPlaying(false);
    } else {
      await audio.play();
      setIsPlaying(true);
    }
  };

  const toggleMute = () => {
    const audio = audioRef.current;
    if (!audio) return;
    audio.muted = !isMuted;
    setIsMuted(!isMuted);
  };

  const handleSeek = (e: React.ChangeEvent<HTMLInputElement>) => {
    const audio = audioRef.current;
    if (!audio) return;
    const time = parseFloat(e.target.value);
    audio.currentTime = time;
    setCurrentTime(time);
  };

  const handleVolumeChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const audio = audioRef.current;
    if (!audio) return;
    const vol = parseFloat(e.target.value);
    audio.volume = vol;
    setVolume(vol);
    setIsMuted(vol === 0);
  };

  const formatTime = (seconds: number) => {
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return `${mins}:${secs.toString().padStart(2, '0')}`;
  };

  return (
    <div className="rounded-xl border border-teal-200 bg-teal-50 p-4">
      <audio ref={audioRef} src={audioUrl} preload="metadata" />

      <div className="flex items-center gap-3 mb-3">
        <button
          onClick={togglePlay}
          aria-label={isPlaying ? t('pause') : t('play')}
          className="flex h-11 w-11 flex-shrink-0 items-center justify-center rounded-full bg-teal-600 text-white hover:bg-teal-700 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500"
        >
          {isPlaying ? (
            <Pause className="h-5 w-5" />
          ) : (
            <Play className="h-5 w-5 translate-x-0.5" />
          )}
        </button>

        <div className="flex-1 min-w-0">
          <p className="text-sm font-medium text-teal-900 truncate">
            {t('audioSummary')} · {language.toUpperCase()}
          </p>
          <div className="flex items-center gap-2 mt-1">
            <span className="text-xs text-teal-700 tabular-nums w-10 flex-shrink-0">
              {formatTime(currentTime)}
            </span>
            <input
              type="range"
              min={0}
              max={duration || 1}
              step={0.1}
              value={currentTime}
              onChange={handleSeek}
              aria-label={t('seekBar')}
              className="h-1.5 flex-1 accent-teal-600 cursor-pointer"
            />
            <span className="text-xs text-teal-700 tabular-nums w-10 flex-shrink-0 text-right">
              {formatTime(duration)}
            </span>
          </div>
        </div>

        <div className="flex items-center gap-1 flex-shrink-0">
          <button
            onClick={toggleMute}
            aria-label={isMuted ? t('unmute') : t('mute')}
            className="flex h-8 w-8 items-center justify-center rounded text-teal-700 hover:text-teal-900 hover:bg-teal-100 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500"
          >
            {isMuted || volume === 0 ? (
              <VolumeX className="h-4 w-4" />
            ) : (
              <Volume2 className="h-4 w-4" />
            )}
          </button>
          <input
            type="range"
            min={0}
            max={1}
            step={0.05}
            value={isMuted ? 0 : volume}
            onChange={handleVolumeChange}
            aria-label={t('volume')}
            className="h-1.5 w-16 accent-teal-600 cursor-pointer hidden sm:block"
          />
        </div>

        <a
          href={downloadUrl}
          download
          aria-label={t('download')}
          className="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded text-teal-700 hover:text-teal-900 hover:bg-teal-100 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500"
        >
          <Download className="h-4 w-4" />
        </a>
      </div>
    </div>
  );
}
