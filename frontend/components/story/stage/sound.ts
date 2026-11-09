/**
 * Sound effects, synthesised with WebAudio: no audio file to download on a
 * 2G connection, and nothing to cache for offline use.
 *
 * Browsers only let a page make sound after the learner has interacted with
 * it, so the AudioContext is created lazily, from the first effect played
 * after a tap. Every failure (no WebAudio, a context the browser refuses) is
 * silent: the story never waits on a sound.
 */

export type Sfx = "pop" | "whoosh" | "correct" | "oops" | "coin" | "fanfare" | "star";

type AudioContextCtor = typeof AudioContext;

let context: AudioContext | null = null;

function audio(): AudioContext | null {
  if (typeof window === "undefined") return null;
  const Ctor: AudioContextCtor | undefined =
    window.AudioContext ??
    (window as unknown as { webkitAudioContext?: AudioContextCtor }).webkitAudioContext;
  if (!Ctor) return null;
  try {
    context ??= new Ctor();
    if (context.state === "suspended") void context.resume().catch(() => {});
    return context;
  } catch {
    return null;
  }
}

/** Call from a tap: lets later effects play without one. */
export function unlockAudio(): void {
  audio();
}

interface ToneOptions {
  freq: number;
  /** Glide to this frequency over the note. */
  to?: number;
  type?: OscillatorType;
  start: number;
  duration: number;
  gain?: number;
}

function tone(ac: AudioContext, out: AudioNode, options: ToneOptions): void {
  const { freq, to, type = "sine", start, duration, gain = 0.2 } = options;
  const osc = ac.createOscillator();
  const env = ac.createGain();
  const t0 = ac.currentTime + start;
  osc.type = type;
  osc.frequency.setValueAtTime(freq, t0);
  if (to) osc.frequency.exponentialRampToValueAtTime(to, t0 + duration);
  env.gain.setValueAtTime(0.0001, t0);
  env.gain.exponentialRampToValueAtTime(gain, t0 + 0.012);
  env.gain.exponentialRampToValueAtTime(0.0001, t0 + duration);
  osc.connect(env).connect(out);
  osc.start(t0);
  osc.stop(t0 + duration + 0.02);
}

function noise(ac: AudioContext, out: AudioNode, start: number, duration: number): void {
  const length = Math.max(1, Math.floor(ac.sampleRate * duration));
  const buffer = ac.createBuffer(1, length, ac.sampleRate);
  const data = buffer.getChannelData(0);
  // A fixed pseudo-random sequence: a whoosh needs no real randomness.
  let seed = 1;
  for (let i = 0; i < length; i += 1) {
    seed = (seed * 16807) % 2147483647;
    data[i] = (seed / 2147483647) * 2 - 1;
  }
  const source = ac.createBufferSource();
  source.buffer = buffer;
  const filter = ac.createBiquadFilter();
  filter.type = "bandpass";
  filter.Q.value = 1.4;
  const t0 = ac.currentTime + start;
  filter.frequency.setValueAtTime(300, t0);
  filter.frequency.exponentialRampToValueAtTime(2400, t0 + duration * 0.6);
  filter.frequency.exponentialRampToValueAtTime(500, t0 + duration);
  const env = ac.createGain();
  env.gain.setValueAtTime(0.0001, t0);
  env.gain.exponentialRampToValueAtTime(0.35, t0 + duration * 0.4);
  env.gain.exponentialRampToValueAtTime(0.0001, t0 + duration);
  source.connect(filter).connect(env).connect(out);
  source.start(t0);
  source.stop(t0 + duration + 0.02);
}

const C5 = 523.25;
const E5 = 659.25;
const G5 = 783.99;
const C6 = 1046.5;
const E6 = 1318.5;

/** Plays one effect. Never throws. */
export function playSfx(name: Sfx): void {
  const ac = audio();
  if (!ac) return;
  try {
    const out = ac.createGain();
    out.gain.value = 0.7;
    out.connect(ac.destination);
    switch (name) {
      case "pop":
        tone(ac, out, { freq: 880, to: 320, type: "sine", start: 0, duration: 0.09, gain: 0.3 });
        break;
      case "whoosh":
        noise(ac, out, 0, 0.42);
        break;
      case "coin":
        tone(ac, out, { freq: 988, type: "square", start: 0, duration: 0.07, gain: 0.08 });
        tone(ac, out, { freq: E6, type: "square", start: 0.07, duration: 0.22, gain: 0.08 });
        break;
      case "correct":
        tone(ac, out, { freq: C5, type: "triangle", start: 0, duration: 0.12, gain: 0.25 });
        tone(ac, out, { freq: E5, type: "triangle", start: 0.1, duration: 0.12, gain: 0.25 });
        tone(ac, out, { freq: G5, type: "triangle", start: 0.2, duration: 0.3, gain: 0.25 });
        break;
      case "oops":
        tone(ac, out, { freq: 392, to: 370, type: "triangle", start: 0, duration: 0.16, gain: 0.25 });
        tone(ac, out, { freq: 311, to: 262, type: "triangle", start: 0.17, duration: 0.3, gain: 0.25 });
        break;
      case "star":
        tone(ac, out, { freq: 1568, to: 2637, type: "sine", start: 0, duration: 0.18, gain: 0.15 });
        tone(ac, out, { freq: 2093, to: 3136, type: "sine", start: 0.08, duration: 0.2, gain: 0.1 });
        break;
      case "fanfare":
        tone(ac, out, { freq: C5, type: "triangle", start: 0, duration: 0.14, gain: 0.25 });
        tone(ac, out, { freq: E5, type: "triangle", start: 0.14, duration: 0.14, gain: 0.25 });
        tone(ac, out, { freq: G5, type: "triangle", start: 0.28, duration: 0.14, gain: 0.25 });
        tone(ac, out, { freq: C6, type: "triangle", start: 0.42, duration: 0.55, gain: 0.28 });
        tone(ac, out, { freq: G5, type: "sine", start: 0.42, duration: 0.55, gain: 0.12 });
        break;
    }
  } catch {
    // A sound effect is never worth an error.
  }
}
