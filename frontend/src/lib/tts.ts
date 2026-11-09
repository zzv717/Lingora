/**
 * Browser text-to-speech (TTS) and speech-to-text (STT) helpers.
 * Runs 100% in the user's browser via the standard Web Speech API (zero cloud latency/cost).
 */

export function speak(text: string, lang = "en-US", voiceName?: string): void {
  if (typeof window === "undefined" || !("speechSynthesis" in window)) return;
  try {
    window.speechSynthesis.cancel();
    const u = new SpeechSynthesisUtterance(text);
    u.lang = lang;
    u.rate = 0.95;
    if (voiceName) {
      const voices = window.speechSynthesis.getVoices();
      const match = voices.find((v) => v.name === voiceName || v.lang === lang);
      if (match) u.voice = match;
    }
    window.speechSynthesis.speak(u);
  } catch {
    /* ignore unsupported environments */
  }
}

export function getEnglishVoices(): SpeechSynthesisVoice[] {
  if (typeof window === "undefined" || !("speechSynthesis" in window)) return [];
  return window.speechSynthesis.getVoices().filter((v) => v.lang.startsWith("en"));
}

export function sttAvailable(): boolean {
  if (typeof window === "undefined") return false;
  return "webkitSpeechRecognition" in window || "SpeechRecognition" in window;
}

export function listenOnce(onResult: (text: string) => void, onError?: (err: string) => void): () => void {
  if (!sttAvailable()) {
    onError?.("Ovozni aniqlash brauzeringizda qo'llab-quvvatlanmaydi.");
    return () => {};
  }
  const win = window as unknown as Record<string, unknown>;
  const Speech = (win.SpeechRecognition || win.webkitSpeechRecognition) as new () => {
    lang: string;
    continuous: boolean;
    interimResults: boolean;
    onresult: (ev: { results?: { [key: number]: { [key: number]: { transcript?: string } } } }) => void;
    onerror: (e: { error?: string }) => void;
    start: () => void;
    stop: () => void;
  };
  const r = new Speech();
  r.lang = "uz-UZ";
  r.continuous = false;
  r.interimResults = false;

  r.onresult = (ev) => {
    const transcript = ev.results?.[0]?.[0]?.transcript || "";
    if (transcript.trim()) onResult(transcript.trim());
  };

  r.onerror = (e) => {
    onError?.(e.error || "Ovoz yozishda xatolik yuz berdi");
  };

  try {
    r.start();
  } catch (err) {
    onError?.("Mikrofonga ulanib bo'lmadi");
  }

  return () => {
    try {
      r.stop();
    } catch {
      /* noop */
    }
  };
}
