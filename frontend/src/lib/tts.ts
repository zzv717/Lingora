"use client";
/** Browser-native text-to-speech (offline, no cloud) for vocabulary listening tasks. */
export function speak(text: string, lang = "en-US", rate = 0.9): Promise<void> {
  return new Promise((resolve) => {
    if (typeof window === "undefined" || !window.speechSynthesis) return resolve();
    try {
      window.speechSynthesis.cancel();
      const u = new SpeechSynthesisUtterance(text);
      u.lang = lang;
      u.rate = rate;
      u.onend = () => resolve();
      u.onerror = () => resolve();
      window.speechSynthesis.speak(u);
      // safety resolve in case onend never fires
      setTimeout(resolve, Math.max(2000, text.length * 120));
    } catch {
      resolve();
    }
  });
}

export function ttsAvailable(): boolean {
  return typeof window !== "undefined" && !!window.speechSynthesis;
}

/** Browser speech recognition (voice input for the AI tutor). Chrome/Edge only. */
export function sttAvailable(): boolean {
  return (
    typeof window !== "undefined" &&
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    !!((window as any).SpeechRecognition || (window as any).webkitSpeechRecognition)
  );
}

export function listenOnce(onResult: (text: string) => void, lang = "uz-UZ"): () => void {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const SR = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
  if (!SR) return () => {};
  const rec = new SR();
  rec.lang = lang;
  rec.interimResults = false;
  rec.maxAlternatives = 1;
  rec.onresult = (e: unknown) => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const res = (e as any).results?.[0]?.[0]?.transcript;
    if (res) onResult(res);
  };
  rec.start();
  return () => {
    try {
      rec.stop();
    } catch {
      /* noop */
    }
  };
}
