/**
 * Read-aloud with the platform's AI voice (#2704).
 *
 * Each line is spoken with OpenAI TTS (the voice lesson audio and the tutor's
 * "listen" button use), one voice per cast member. The server caches each
 * clip, so a line heard before by anyone plays at once. A line whose clip
 * can't be had (offline, daily cap, error, autoplay refused) is read by the
 * browser's own speech synthesis instead, so read-aloud never goes silent
 * where it worked before.
 *
 * Fire-and-forget: nothing in the story waits for a line to finish. Lines play
 * one after the other; a new `speak` or `stopSpeaking` cuts the current one.
 */

import { apiFetch } from "@/lib/api";

/** The server's voice profiles (`app/api/v1/schemas/story_audio.py`). */
export type VoiceProfile = "narrator" | "girl" | "boy" | "woman" | "man" | "tutor";

export interface SpeechVoice {
  pitch?: number;
  rate?: number;
  /** The AI voice. Without one, the line is read by the narrator. */
  profile?: VoiceProfile;
}

const AI_LANGUAGES = new Set(["fr", "en"]);
const MAX_LINE_CHARS = 600;

function synthAvailable(): boolean {
  return (
    typeof window !== "undefined" &&
    "speechSynthesis" in window &&
    !!window.speechSynthesis &&
    typeof window.SpeechSynthesisUtterance === "function"
  );
}

function audioAvailable(): boolean {
  return typeof window !== "undefined" && typeof window.Audio === "function";
}

/** Whether this browser can read aloud at all, by either voice. */
export function speechAvailable(): boolean {
  return audioAvailable() || synthAvailable();
}

/* -------------------------------------------------------------------------- */
/* AI clips                                                                    */
/* -------------------------------------------------------------------------- */

/** One promise per line and voice: a prefetch and a play share the request. */
const clipUrls = new Map<string, Promise<string | null>>();

function cleanLine(line: string): string {
  return line.replace(/\s+/g, " ").trim();
}

function clipKey(text: string, lang: string, profile: VoiceProfile): string {
  return `${profile}\u001f${lang}\u001f${text}`;
}

/** The clip URL of one line, or null when the browser voice must read it. */
function clipUrl(text: string, lang: string, profile: VoiceProfile): Promise<string | null> {
  if (!AI_LANGUAGES.has(lang) || text.length > MAX_LINE_CHARS || !audioAvailable()) {
    return Promise.resolve(null);
  }
  if (typeof navigator !== "undefined" && navigator.onLine === false) return Promise.resolve(null);
  const key = clipKey(text, lang, profile);
  const known = clipUrls.get(key);
  if (known) return known;
  const request = apiFetch<{ url: string }>("/api/v1/story-audio", {
    method: "POST",
    body: JSON.stringify({ text, language: lang, voice: profile }),
  })
    .then((res) => (typeof res?.url === "string" && res.url.startsWith("/api/v1/story-audio/") ? res.url : null))
    .catch(() => null);
  clipUrls.set(key, request);
  // A failure is not remembered: the next time, the line is asked for again.
  void request.then((url) => {
    if (url === null) clipUrls.delete(key);
  });
  return request;
}

/** Asks the server for the clips of lines about to be read, so they play at once. */
export function prefetchSpeech(lines: string[], lang: string, voice: SpeechVoice = {}): void {
  const profile = voice.profile ?? "narrator";
  for (const line of lines) {
    const clean = cleanLine(line);
    if (clean) void clipUrl(clean, lang, profile);
  }
}


/* -------------------------------------------------------------------------- */
/* Playback                                                                    */
/* -------------------------------------------------------------------------- */

/** Bumped by every `speak` and `stopSpeaking`: a run that sees a newer one stops. */
let generation = 0;
let player: HTMLAudioElement | null = null;
/** Whether the player has played once: iOS lets it play on its own from then on. */
let unlocked = false;

function audioElement(): HTMLAudioElement {
  if (!player) {
    player = new window.Audio();
    player.preload = "auto";
  }
  return player;
}

/** Ends the clip being played, if any (set by `playClip`). */
let cancelClip: (() => void) | null = null;

/** Plays one clip to its end. False when it could not be played. */
function playClip(url: string, run: number): Promise<boolean> {
  return new Promise((resolve) => {
    if (run !== generation) return resolve(true);
    const audio = audioElement();
    let settled = false;
    const onEnded = () => done(true);
    const onError = () => done(false);
    function done(ok: boolean) {
      if (settled) return;
      settled = true;
      audio.removeEventListener("ended", onEnded);
      audio.removeEventListener("error", onError);
      if (cancelClip === cancel) cancelClip = null;
      resolve(ok);
    }
    const cancel = () => done(true);
    cancelClip = cancel;
    audio.addEventListener("ended", onEnded);
    audio.addEventListener("error", onError);
    audio.src = url;
    try {
      const started = audio.play();
      if (started && typeof started.then === "function") {
        started.then(
          () => {
            unlocked = true;
          },
          () => done(false),
        );
      }
    } catch {
      done(false);
    }
  });
}

function languageTag(lang: string): string {
  if (lang === "fr") return "fr-FR";
  if (lang === "en") return "en-GB";
  return lang;
}

function synthVoiceFor(lang: string): SpeechSynthesisVoice | undefined {
  try {
    const voices = window.speechSynthesis.getVoices();
    const matching = voices.filter((voice) => voice.lang?.toLowerCase().startsWith(lang.toLowerCase()));
    return matching.find((voice) => voice.localService) ?? matching[0];
  } catch {
    return undefined;
  }
}

/** Reads one line with the browser's voice, resolving when it is done. */
function synthLine(text: string, lang: string, voice: SpeechVoice, run: number): Promise<void> {
  return new Promise((resolve) => {
    if (run !== generation || !synthAvailable()) return resolve();
    try {
      const chosen = synthVoiceFor(lang);
      const utterance = new window.SpeechSynthesisUtterance(text);
      utterance.lang = chosen?.lang ?? languageTag(lang);
      if (chosen) utterance.voice = chosen;
      utterance.pitch = Math.min(2, Math.max(0, voice.pitch ?? 1));
      utterance.rate = Math.min(2, Math.max(0.5, voice.rate ?? 1));
      utterance.onend = () => resolve();
      utterance.onerror = () => resolve();
      window.speechSynthesis.speak(utterance);
    } catch {
      resolve();
    }
  });
}

/**
 * Makes the clip player usable from now on. Call it in a tap handler: iOS only
 * lets an `<audio>` element play on its own once it has played in a gesture.
 */
export function unlockSpeech(): void {
  if (!audioAvailable()) return;
  try {
    if (unlocked) return;
    const audio = audioElement();
    // A tiny silent WAV, played (and cut) within the tap.
    audio.src = "data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEAQB8AAIA+AAACABAAZGF0YQAAAAA=";
    const started = audio.play();
    if (started && typeof started.then === "function") {
      started.then(
        () => {
          unlocked = true;
        },
        () => undefined,
      );
    }
  } catch {
    // Read-aloud then falls back to the browser's voice.
  }
}

/** Stops reading and forgets every clip URL and the player (tests). */
export function resetSpeech(): void {
  stopSpeaking();
  clipUrls.clear();
  player = null;
  unlocked = false;
}

/** Stops whatever is being read. */
export function stopSpeaking(): void {
  generation += 1;
  cancelClip?.();
  if (player) {
    try {
      player.pause();
    } catch {
      // Nothing to stop.
    }
  }
  if (synthAvailable()) {
    try {
      window.speechSynthesis.cancel();
    } catch {
      // Nothing to stop.
    }
  }
}

async function run(lines: string[], lang: string, voice: SpeechVoice, current: number): Promise<void> {
  const profile = voice.profile ?? "narrator";
  // Every clip is asked for at once; they play in order.
  const urls = lines.map((line) => clipUrl(line, lang, profile));
  for (let i = 0; i < lines.length; i += 1) {
    if (current !== generation) return;
    const url = await urls[i];
    if (current !== generation) return;
    const played = url ? await playClip(url, current) : false;
    if (!played) await synthLine(lines[i], lang, voice, current);
  }
}

/** Reads `lines` in `lang` with one character's voice, cutting what was being read. */
export function speak(lines: string[], lang: string, voice: SpeechVoice = {}): void {
  if (!speechAvailable()) return;
  stopSpeaking();
  const current = generation;
  const clean = lines.map(cleanLine).filter(Boolean);
  if (!clean.length) return;
  run(clean, lang, voice, current).catch(() => {
    // Read-aloud is a bonus; the text is on screen either way.
  });
}
