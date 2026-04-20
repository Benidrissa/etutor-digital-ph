'use client';

import { useState, useRef, useEffect, useCallback } from 'react';
import { useTranslations, useLocale } from 'next-intl';
import { Send, Paperclip, Mic, Loader2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import {
  uploadTutorFile,
  saveDraft,
  loadDraft,
  clearDraft,
  transcribeAudio,
} from '@/lib/tutor-api';
import { FilePreview, type PendingFile } from '@/components/chat/file-preview';

function pickRecorderMimeType(): string {
  if (typeof MediaRecorder === 'undefined') return '';
  const candidates = [
    'audio/webm;codecs=opus',
    'audio/webm',
    'audio/mp4',
    'audio/ogg;codecs=opus',
  ];
  return candidates.find((t) => MediaRecorder.isTypeSupported(t)) ?? '';
}

const ACCEPTED_TYPES = [
  'image/png',
  'image/jpeg',
  'image/jpg',
  'image/webp',
  'image/gif',
  'application/pdf',
  'text/csv',
  'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  'text/plain',
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
].join(',');

const MAX_SIZE_BYTES = 10 * 1024 * 1024;

export interface AttachedFileInfo {
  fileId: string;
  name: string;
  mimeType: string;
  sizeBytes: number;
}

interface ChatInputProps {
  onSendMessage: (message: string, attachedFiles: AttachedFileInfo[]) => void;
  disabled?: boolean;
  placeholder?: string;
  conversationId?: string | null;
}

function generateLocalId(): string {
  return `${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

export function ChatInput({ onSendMessage, disabled = false, placeholder, conversationId = null }: ChatInputProps) {
  const t = useTranslations('ChatTutor');
  const locale = useLocale();
  const [message, setMessage] = useState(() => loadDraft(conversationId));
  const [pendingFiles, setPendingFiles] = useState<PendingFile[]>([]);
  const [isDragging, setIsDragging] = useState(false);
  const [isRecording, setIsRecording] = useState(false);
  const [isTranscribing, setIsTranscribing] = useState(false);
  const [micError, setMicError] = useState<string | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const draftTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const conversationIdRef = useRef<string | null>(conversationId);
  const messageRef = useRef(message);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const audioChunksRef = useRef<Blob[]>([]);
  const audioStreamRef = useRef<MediaStream | null>(null);
  const recordingAbortedRef = useRef(false);

  useEffect(() => {
    conversationIdRef.current = conversationId;
  }, [conversationId]);

  useEffect(() => {
    messageRef.current = message;
  }, [message]);

  const actualPlaceholder = placeholder || t('placeholder');

  // Debounced draft save on every keystroke
  useEffect(() => {
    if (draftTimerRef.current) clearTimeout(draftTimerRef.current);
    draftTimerRef.current = setTimeout(() => {
      saveDraft(conversationIdRef.current, message);
    }, 300);
    return () => {
      if (draftTimerRef.current) clearTimeout(draftTimerRef.current);
    };
  }, [message]);

  // Flush draft on unmount (conversation switch, panel close) and beforeunload
  useEffect(() => {
    const flush = () => {
      if (draftTimerRef.current) clearTimeout(draftTimerRef.current);
      saveDraft(conversationIdRef.current, messageRef.current);
    };
    window.addEventListener('beforeunload', flush);
    return () => {
      window.removeEventListener('beforeunload', flush);
      flush();
    };
  }, []);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const trimmedMessage = message.trim();
    const readyFiles = pendingFiles.filter((f) => f.fileId && !f.error);

    if ((trimmedMessage || readyFiles.length > 0) && !disabled) {
      const attachedFiles: AttachedFileInfo[] = readyFiles.map((f) => ({
        fileId: f.fileId!,
        name: f.file.name,
        mimeType: f.file.type,
        sizeBytes: f.file.size,
      }));
      clearDraft(conversationIdRef.current);
      if (draftTimerRef.current) clearTimeout(draftTimerRef.current);
      onSendMessage(trimmedMessage || ' ', attachedFiles);
      setMessage('');
      setPendingFiles([]);
      if (textareaRef.current) {
        textareaRef.current.style.height = 'auto';
      }
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit(e);
    }
  };

  useEffect(() => {
    const textarea = textareaRef.current;
    if (textarea) {
      textarea.style.height = 'auto';
      const newHeight = Math.min(textarea.scrollHeight, 120);
      textarea.style.height = `${newHeight}px`;
    }
  }, [message]);

  const processFile = useCallback(
    async (file: File) => {
      const localId = generateLocalId();
      let previewUrl: string | undefined;

      if (file.type.startsWith('image/')) {
        previewUrl = URL.createObjectURL(file);
      }

      let errorMsg: string | undefined;
      if (file.size > MAX_SIZE_BYTES) {
        errorMsg = t('fileUpload.tooLarge');
      } else if (!ACCEPTED_TYPES.includes(file.type)) {
        errorMsg = t('fileUpload.unsupportedType');
      }

      const newFile: PendingFile = {
        localId,
        file,
        previewUrl,
        uploading: !errorMsg,
        progress: 0,
        error: errorMsg,
      };

      setPendingFiles((prev) => [...prev, newFile]);

      if (errorMsg) return;

      try {
        const result = await uploadTutorFile(file, (percent) => {
          setPendingFiles((prev) =>
            prev.map((f) => (f.localId === localId ? { ...f, progress: percent } : f))
          );
        });

        setPendingFiles((prev) =>
          prev.map((f) =>
            f.localId === localId ? { ...f, uploading: false, progress: 100, fileId: result.file_id } : f
          )
        );
      } catch (err) {
        const isDailyLimit = err instanceof Error && err.message === 'DAILY_LIMIT_REACHED';
        setPendingFiles((prev) =>
          prev.map((f) =>
            f.localId === localId
              ? {
                  ...f,
                  uploading: false,
                  error: isDailyLimit ? t('fileUpload.dailyLimitReached') : t('fileUpload.uploadFailed'),
                }
              : f
          )
        );
      }
    },
    [t]
  );

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (!files) return;
    Array.from(files).forEach(processFile);
    e.target.value = '';
  };

  const stopAudioStream = useCallback(() => {
    audioStreamRef.current?.getTracks().forEach((track) => track.stop());
    audioStreamRef.current = null;
  }, []);

  const startRecording = useCallback(async () => {
    if (disabled || isRecording || isTranscribing) return;
    if (typeof navigator === 'undefined' || !navigator.mediaDevices?.getUserMedia) {
      setMicError(t('voice.unsupported'));
      return;
    }
    if (typeof MediaRecorder === 'undefined') {
      setMicError(t('voice.unsupported'));
      return;
    }

    setMicError(null);
    recordingAbortedRef.current = false;

    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true },
      });
      audioStreamRef.current = stream;

      const mimeType = pickRecorderMimeType();
      const recorder = mimeType ? new MediaRecorder(stream, { mimeType }) : new MediaRecorder(stream);
      mediaRecorderRef.current = recorder;
      audioChunksRef.current = [];

      recorder.ondataavailable = (event) => {
        if (event.data && event.data.size > 0) audioChunksRef.current.push(event.data);
      };

      recorder.onstop = async () => {
        const chunks = audioChunksRef.current;
        audioChunksRef.current = [];
        stopAudioStream();
        mediaRecorderRef.current = null;
        setIsRecording(false);

        if (recordingAbortedRef.current || chunks.length === 0) return;

        const audioBlob = new Blob(chunks, { type: recorder.mimeType || 'audio/webm' });
        if (audioBlob.size < 1000) {
          setMicError(t('voice.tooShort'));
          return;
        }

        setIsTranscribing(true);
        try {
          const transcript = await transcribeAudio(audioBlob, locale);
          if (transcript) {
            setMessage((prev) => (prev ? `${prev.trimEnd()} ${transcript}` : transcript));
            textareaRef.current?.focus();
          } else {
            setMicError(t('voice.noSpeech'));
          }
        } catch (err) {
          const code = err instanceof Error ? err.message : '';
          if (code === 'RECORDING_TOO_LARGE') setMicError(t('voice.tooLarge'));
          else if (code === 'TRANSCRIBE_UNAVAILABLE') setMicError(t('voice.unavailable'));
          else setMicError(t('voice.failed'));
        } finally {
          setIsTranscribing(false);
        }
      };

      recorder.start();
      setIsRecording(true);
    } catch (err) {
      stopAudioStream();
      mediaRecorderRef.current = null;
      setIsRecording(false);
      const name = err instanceof Error ? err.name : '';
      if (name === 'NotAllowedError' || name === 'SecurityError') {
        setMicError(t('voice.permissionDenied'));
      } else if (name === 'NotFoundError') {
        setMicError(t('voice.noMicrophone'));
      } else {
        setMicError(t('voice.failed'));
      }
    }
  }, [disabled, isRecording, isTranscribing, locale, stopAudioStream, t]);

  const stopRecording = useCallback((abort = false) => {
    const recorder = mediaRecorderRef.current;
    if (!recorder) return;
    recordingAbortedRef.current = abort;
    if (recorder.state !== 'inactive') recorder.stop();
  }, []);

  useEffect(() => {
    return () => {
      recordingAbortedRef.current = true;
      if (mediaRecorderRef.current && mediaRecorderRef.current.state !== 'inactive') {
        mediaRecorderRef.current.stop();
      }
      stopAudioStream();
    };
  }, [stopAudioStream]);

  const handleRemoveFile = (localId: string) => {
    setPendingFiles((prev) => {
      const removed = prev.find((f) => f.localId === localId);
      if (removed?.previewUrl) URL.revokeObjectURL(removed.previewUrl);
      return prev.filter((f) => f.localId !== localId);
    });
  };

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(true);
  };

  const handleDragLeave = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
    const files = e.dataTransfer.files;
    if (!files) return;
    Array.from(files).forEach(processFile);
  };

  const hasReadyFiles = pendingFiles.some((f) => f.fileId && !f.error);
  const isUploading = pendingFiles.some((f) => f.uploading);
  const canSend = (message.trim() || hasReadyFiles) && !disabled && !isUploading;

  return (
    <div
      className={cn(
        'border-t bg-background transition-colors',
        isDragging && 'bg-primary/5 border-primary'
      )}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
    >
      {isDragging && (
        <div className="flex items-center justify-center py-3 text-sm text-primary font-medium">
          {t('fileUpload.dragDrop')}
        </div>
      )}

      {pendingFiles.length > 0 && (
        <div className="flex flex-col gap-1.5 px-4 pt-3">
          {pendingFiles.map((pf) => (
            <FilePreview key={pf.localId} pendingFile={pf} onRemove={handleRemoveFile} />
          ))}
        </div>
      )}

      {micError && (
        <div
          role="alert"
          className="px-4 pt-2 text-xs text-destructive"
          onClick={() => setMicError(null)}
        >
          {micError}
        </div>
      )}

      <form onSubmit={handleSubmit} className="flex items-end gap-2 p-4">
        <input
          ref={fileInputRef}
          type="file"
          accept={ACCEPTED_TYPES}
          multiple
          onChange={handleFileChange}
          className="sr-only"
          aria-hidden="true"
          capture="environment"
        />

        <div className="flex flex-col shrink-0">
          <Button
            type="button"
            variant={isRecording ? 'destructive' : 'ghost'}
            size="icon"
            className="min-h-[44px] min-w-[44px]"
            aria-label={
              isRecording
                ? t('voice.releaseToSend')
                : isTranscribing
                  ? t('voice.transcribing')
                  : t('voice.holdToTalk')
            }
            aria-pressed={isRecording}
            disabled={disabled || isTranscribing}
            onPointerDown={(e) => {
              e.preventDefault();
              startRecording();
            }}
            onPointerUp={() => stopRecording(false)}
            onPointerLeave={() => {
              if (isRecording) stopRecording(false);
            }}
            onPointerCancel={() => stopRecording(true)}
          >
            {isTranscribing ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Mic className={cn('h-4 w-4', isRecording && 'animate-pulse')} />
            )}
          </Button>

          <Button
            type="button"
            variant="ghost"
            size="icon"
            className="min-h-[44px] min-w-[44px]"
            aria-label={t('fileUpload.attachAriaLabel')}
            disabled={disabled}
            onClick={() => fileInputRef.current?.click()}
          >
            <Paperclip className="h-4 w-4" />
          </Button>
        </div>

        <div className="flex-1 relative">
          <textarea
            ref={textareaRef}
            value={message}
            onChange={(e) => setMessage(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={actualPlaceholder}
            disabled={disabled}
            rows={1}
            className={cn(
              'w-full resize-none rounded-md border border-input px-3 py-2',
              'text-sm bg-background placeholder:text-muted-foreground',
              'focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2',
              'min-h-[44px] max-h-[120px]',
              disabled && 'opacity-50 cursor-not-allowed'
            )}
            style={{
              lineHeight: '1.4',
              fontSize: '16px',
            }}
          />
        </div>

        <Button
          type="submit"
          size="icon"
          disabled={!canSend}
          className="min-h-[44px] min-w-[44px] shrink-0"
          aria-label={t('send')}
        >
          <Send className="h-4 w-4" />
        </Button>
      </form>
    </div>
  );
}
