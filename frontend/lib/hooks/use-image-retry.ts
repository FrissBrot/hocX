"use client";

import { useCallback, useEffect, useState } from "react";

// Vorschaubilder (Galerie, Dateien, Alben, Upload-Verlauf, öffentliche Links) laden über ein
// schlichtes <img>. Ein einzelner Fehlschlag ist meist vorübergehend: 503 `thumbnail_busy`
// (Vorschau wird gerade erzeugt, file_service CONC-014), 503 `db_busy`/`overloaded` unter Last,
// 429 oder ein abgebrochener Request. Früher blieb die Kachel danach auf «Vorschau nicht
// verfügbar», bis die virtualisierte Galerie sie neu montierte (Bug 1.6). Darum: begrenzt
// wiederholen, mit wachsendem Abstand und Zufallsanteil, damit nicht alle Kacheln eines Rasters
// im selben Moment erneut anfragen. Das Backend antwortet mit Retry-After: 5 - der zweite
// Abstand liegt deshalb bewusst darüber.

/** Abstände vor dem 2., 3. und 4. Versuch (also höchstens 4 Requests je Bild). */
export const IMAGE_RETRY_DELAYS_MS: readonly number[] = [2000, 5000, 10000];
/** Zufallsanteil: ±25 % je Abstand. */
const JITTER = 0.25;

export function jitteredDelay(baseMs: number, random: () => number = Math.random): number {
  return Math.round(baseMs * (1 - JITTER + random() * 2 * JITTER));
}

/** Neue URL je Versuch: der Browser lädt dieselbe, eben fehlgeschlagene URL sonst nicht erneut. */
export function withRetryParam(url: string, attempt: number): string {
  if (attempt <= 0) return url;
  return `${url}${url.includes("?") ? "&" : "?"}retry=${attempt}`;
}

export type ImageRetryState = {
  /** Aktuell zu ladende URL (null, wenn es keine Vorschau gibt). */
  src: string | null;
  /** Zählt ab 0; jeder neue Versuch bekommt eine eigene URL. */
  attempt: number;
  /** Fehlschlag, nächster Versuch ist geplant: neutraler Ladezustand, kein Platzhaltertext. */
  waiting: boolean;
  /** Alle Versuche gescheitert: jetzt erst den Platzhalter zeigen. */
  failed: boolean;
  onError: () => void;
};

type Phase = "loading" | "waiting" | "failed";

export function useImageRetry(
  url: string | null | undefined,
  { delays = IMAGE_RETRY_DELAYS_MS, random }: { delays?: readonly number[]; random?: () => number } = {},
): ImageRetryState {
  const key = url ?? null;
  const [state, setState] = useState<{ key: string | null; attempt: number; phase: Phase }>({ key, attempt: 0, phase: "loading" });
  // Andere Ausgangs-URL (anderes Bild): von vorn beginnen, ohne zusätzlichen Render mit altem Zustand.
  const current = state.key === key ? state : { key, attempt: 0, phase: "loading" as Phase };
  if (current !== state) setState(current);

  const { attempt, phase } = current;
  const delay = delays[attempt];

  useEffect(() => {
    if (phase !== "waiting" || delay === undefined) return;
    // Beim Unmount bzw. Wechsel der URL läuft kein weiterer Versuch mehr an.
    const timer = window.setTimeout(() => {
      setState((prev) => (prev.key === key && prev.phase === "waiting" ? { key, attempt: prev.attempt + 1, phase: "loading" } : prev));
    }, jitteredDelay(delay, random));
    return () => window.clearTimeout(timer);
  }, [phase, delay, key, random]);

  const onError = useCallback(() => {
    setState((prev) => {
      if (prev.key !== key || prev.phase !== "loading") return prev;
      return { key, attempt: prev.attempt, phase: prev.attempt < delays.length ? "waiting" : "failed" };
    });
  }, [key, delays]);

  return {
    src: key === null ? null : withRetryParam(key, attempt),
    attempt,
    waiting: phase === "waiting",
    failed: key !== null && phase === "failed",
    onError,
  };
}
