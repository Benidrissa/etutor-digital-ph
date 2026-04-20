"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { Loader2, Mic, Square, Trash2, Upload } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  deleteQBankQuestionAudio,
  getQBankQuestionAudio,
  uploadQBankQuestionAudio,
  type QBankAudioLanguage,
  type QBankQuestionAudioStatus,
} from "@/lib/api";

const LANGUAGES: QBankAudioLanguage[] = ["fr", "mos", "dyu", "bam", "ful"];

// Matches backend cap in backend/app/api/v1/qbank.py (#1747).
const MAX_UPLOAD_BYTES = 5 * 1024 * 1024;

const ACCEPTED_MIME = [
  "audio/webm",
  "audio/ogg",
  "audio/opus",
  "audio/mpeg",
  "audio/mp3",
  "audio/mp4",
  "audio/x-m4a",
  "audio/m4a",
  "audio/aac",
  "audio/wav",
  "audio/wave",
  "audio/x-wav",
];

interface Props {
  questionId: string;
}

/**
 * Admin-side audio manager for one question: lets the editor record
 * (via MediaRecorder) or upload a pre-made audio file per language,
 * replacing the TTS clip. Manual recordings are never overwritten by
 * batch TTS regeneration — see QBankAudioService.batch_generate (#1747).
 *
 * Falls back gracefully when MediaRecorder isn't available (older
 * Safari, insecure origin) — only the Upload button is shown.
 */
export function QBankAudioManager({ questionId }: Props) {
  const t = useTranslations("qbank");
  const tLang = useTranslations("qbank.audioLanguages");
  const [language, setLanguage] = useState<QBankAudioLanguage>("fr");
  const [status, setStatus] = useState<QBankQuestionAudioStatus | null>(null);
  const [loading, setLoading] = useState(false);
  const [recording, setRecording] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [canRecord, setCanRecord] = useState(false);
  const [recordingSeconds, setRecordingSeconds] = useState(0);

  const recorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<BlobPart[]>([]);
  const streamRef = useRef<MediaStream | null>(null);
  const tickRef = useRef<number | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    // getUserMedia requires HTTPS (except on localhost) and MediaRecorder
    // is unavailable on iOS Safari < 14.5 — detect once on mount.
    if (typeof window === "undefined") return;
    const mediaDevices = window.navigator.mediaDevices;
    const hasGetUser =
      !!mediaDevices && typeof mediaDevices.getUserMedia === "function";
    const hasRecorder = typeof window.MediaRecorder !== "undefined";
    setCanRecord(hasGetUser && hasRecorder);
  }, []);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const s = await getQBankQuestionAudio(questionId, language);
      setStatus(s);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Fetch failed");
    } finally {
      setLoading(false);
    }
  }, [questionId, language]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  function stopRecordingTicker() {
    if (tickRef.current !== null) {
      window.clearInterval(tickRef.current);
      tickRef.current = null;
    }
  }

  function releaseStream() {
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
  }

  async function startRecording() {
    setError(null);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;
      const mime =
        MediaRecorder.isTypeSupported("audio/webm;codecs=opus")
          ? "audio/webm;codecs=opus"
          : MediaRecorder.isTypeSupported("audio/webm")
            ? "audio/webm"
            : MediaRecorder.isTypeSupported("audio/mp4")
              ? "audio/mp4"
              : "";
      const recorder = mime
        ? new MediaRecorder(stream, { mimeType: mime })
        : new MediaRecorder(stream);
      chunksRef.current = [];
      recorder.ondataavailable = (event) => {
        if (event.data.size > 0) chunksRef.current.push(event.data);
      };
      recorder.onstop = async () => {
        stopRecordingTicker();
        releaseStream();
        const blobType = recorder.mimeType || "audio/webm";
        const blob = new Blob(chunksRef.current, { type: blobType });
        chunksRef.current = [];
        setRecording(false);
        if (blob.size === 0) {
          setError(t("audioRecordEmpty"));
          return;
        }
        if (blob.size > MAX_UPLOAD_BYTES) {
          setError(t("audioTooLarge"));
          return;
        }
        await persistBlob(blob, `recording-${language}.webm`);
      };
      recorder.start();
      recorderRef.current = recorder;
      setRecording(true);
      setRecordingSeconds(0);
      tickRef.current = window.setInterval(() => {
        setRecordingSeconds((s) => s + 1);
      }, 1000);
    } catch (err) {
      releaseStream();
      setError(
        err instanceof Error && err.name === "NotAllowedError"
          ? t("audioMicDenied")
          : t("audioRecordFailed"),
      );
      setRecording(false);
    }
  }

  function stopRecording() {
    const recorder = recorderRef.current;
    if (recorder && recorder.state !== "inactive") {
      recorder.stop();
    }
  }

  async function persistBlob(blob: Blob, filename: string) {
    setLoading(true);
    setError(null);
    try {
      const next = await uploadQBankQuestionAudio(
        questionId,
        language,
        blob,
        filename,
      );
      setStatus(next);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload failed");
    } finally {
      setLoading(false);
    }
  }

  async function onFilePicked(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = ""; // allow re-picking the same file next time
    if (!file) return;
    if (file.size > MAX_UPLOAD_BYTES) {
      setError(t("audioTooLarge"));
      return;
    }
    const declared = (file.type || "").toLowerCase();
    if (declared && !ACCEPTED_MIME.includes(declared)) {
      setError(t("audioUnsupportedType"));
      return;
    }
    await persistBlob(file, file.name);
  }

  async function handleDelete() {
    if (!confirm(t("audioDeleteConfirm"))) return;
    setLoading(true);
    setError(null);
    try {
      await deleteQBankQuestionAudio(questionId, language);
      setStatus(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Delete failed");
    } finally {
      setLoading(false);
    }
  }

  const audioUrl = status?.audio_url ?? null;
  const source = status?.source ?? "tts";

  return (
    <div className="space-y-3 rounded-md border bg-gray-50 p-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm font-medium">{t("audioSectionLabel")}</span>
        <div className="flex flex-wrap gap-1">
          {LANGUAGES.map((lang) => (
            <button
              key={lang}
              type="button"
              onClick={() => setLanguage(lang)}
              className={
                "rounded-md border px-2 py-1 text-xs font-medium transition " +
                (language === lang
                  ? "border-primary bg-primary text-primary-foreground"
                  : "border-gray-300 bg-white text-gray-700 hover:border-gray-400")
              }
            >
              {tLang(lang)}
            </button>
          ))}
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        {audioUrl ? (
          <audio
            key={audioUrl}
            controls
            preload="none"
            src={audioUrl}
            className="h-9 max-w-full"
          >
            <track kind="captions" />
          </audio>
        ) : (
          <span className="text-xs text-gray-600">
            {status?.status === "generating"
              ? t("audioGenerating")
              : t("audioNoClip")}
          </span>
        )}
        {audioUrl && (
          <span
            className={
              "rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase " +
              (source === "manual"
                ? "border-emerald-500 bg-emerald-50 text-emerald-700"
                : "border-gray-300 bg-white text-gray-600")
            }
          >
            {source === "manual" ? t("audioSourceManual") : t("audioSourceTts")}
          </span>
        )}
      </div>

      <div className="flex flex-wrap gap-2">
        {canRecord &&
          (recording ? (
            <Button
              type="button"
              variant="destructive"
              size="sm"
              onClick={stopRecording}
              disabled={loading}
            >
              <Square className="mr-2 h-4 w-4" />
              {t("audioStopRecording")} ({recordingSeconds}s)
            </Button>
          ) : (
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={startRecording}
              disabled={loading}
            >
              <Mic className="mr-2 h-4 w-4" />
              {t("audioRecord")}
            </Button>
          ))}
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() => fileInputRef.current?.click()}
          disabled={loading || recording}
        >
          <Upload className="mr-2 h-4 w-4" />
          {t("audioUpload")}
        </Button>
        <input
          ref={fileInputRef}
          type="file"
          accept="audio/*"
          className="hidden"
          onChange={onFilePicked}
        />
        {audioUrl && (
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={handleDelete}
            disabled={loading || recording}
          >
            <Trash2 className="mr-2 h-4 w-4" />
            {t("audioDelete")}
          </Button>
        )}
        {loading && <Loader2 className="h-4 w-4 animate-spin text-gray-500" />}
      </div>

      {!canRecord && (
        <p className="text-xs text-gray-500">{t("audioRecordUnsupported")}</p>
      )}
      {error && <p className="text-sm text-red-700">{error}</p>}
    </div>
  );
}
