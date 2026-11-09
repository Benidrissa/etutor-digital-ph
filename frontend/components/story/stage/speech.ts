/**
 * Read-aloud through the browser's own speech synthesis.
 *
 * Feature-detected and fire-and-forget: a browser without it (or without a
 * voice for the language) simply stays quiet, and nothing in the story waits
 * for a line to finish being spoken. Lines queue in the browser, so a
 * concept's title and rows are read one after the other.
 */

export interface SpeechVoice {
  pitch?: number;
  rate?: number;
}

export function speechAvailable(): boolean {
  return (
    typeof window !== "undefined" &&
    "speechSynthesis" in window &&
    typeof window.SpeechSynthesisUtterance === "function"
  );
}

/** A full language tag the engines know, from the story's two-letter code. */
function languageTag(lang: string): string {
  if (lang === "fr") return "fr-FR";
  if (lang === "en") return "en-GB";
  return lang;
}

function voiceFor(lang: string): SpeechSynthesisVoice | undefined {
  try {
    const voices = window.speechSynthesis.getVoices();
    const matching = voices.filter((voice) => voice.lang?.toLowerCase().startsWith(lang.toLowerCase()));
    return matching.find((voice) => voice.localService) ?? matching[0];
  } catch {
    return undefined;
  }
}

/** Stops whatever is being read. */
export function stopSpeaking(): void {
  if (!speechAvailable()) return;
  try {
    window.speechSynthesis.cancel();
  } catch {
    // Nothing to stop.
  }
}

/** Queues `lines` to be read in `lang` with one character's voice. */
export function speak(lines: string[], lang: string, voice: SpeechVoice = {}): void {
  if (!speechAvailable()) return;
  try {
    const synth = window.speechSynthesis;
    const chosen = voiceFor(lang);
    for (const line of lines) {
      const clean = line.replace(/\s+/g, " ").trim();
      if (!clean) continue;
      const utterance = new window.SpeechSynthesisUtterance(clean);
      utterance.lang = chosen?.lang ?? languageTag(lang);
      if (chosen) utterance.voice = chosen;
      utterance.pitch = Math.min(2, Math.max(0, voice.pitch ?? 1));
      utterance.rate = Math.min(2, Math.max(0.5, voice.rate ?? 1));
      synth.speak(utterance);
    }
  } catch {
    // Read-aloud is a bonus; the text is on screen either way.
  }
}
