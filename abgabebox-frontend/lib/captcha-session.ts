// Captcha-Sitzungs-Token je Abgabe-Link, solange die Seite geladen ist: beim Wechsel zwischen
// Elementen (clientseitige Navigation) bleibt das Modul bestehen, die Sicherheitsprüfung läuft
// also nur einmal pro Seitenaufruf. Ein Neuladen leert den Speicher. Nie auf dem Server
// verwenden: dort teilten sich alle Anfragen dasselbe Modul.

type StoredSession = { token: string; expiresAt: number };

// Etwas Puffer, damit ein Token nicht kurz vor dem Ablauf noch für einen langen Upload genutzt wird
const EXPIRY_MARGIN_MS = 60_000;

const sessions = new Map<string, StoredSession>();

export function readCaptchaSession(linkToken: string, now = Date.now()): string | null {
  if (typeof window === "undefined") return null;
  const stored = sessions.get(linkToken);
  if (!stored) return null;
  if (stored.expiresAt - EXPIRY_MARGIN_MS <= now) {
    sessions.delete(linkToken);
    return null;
  }
  return stored.token;
}

export function storeCaptchaSession(linkToken: string, token: string, expiresInSeconds: number, now = Date.now()) {
  if (typeof window === "undefined") return;
  sessions.set(linkToken, { token, expiresAt: now + expiresInSeconds * 1000 });
}

export function clearCaptchaSession(linkToken: string) {
  sessions.delete(linkToken);
}
