// Installationshinweis für hocX als App (PWA, app/manifest.ts). Reine Hilfsfunktionen, damit die
// Erkennung ohne Browser testbar ist (install.test.ts).

export type InstallPlatform = "ios" | "android" | null;

/** Plattform, der wir die Installation vorschlagen: iPhone/iPad (auch iPadOS, das sich als Mac
 * ausgibt) und Android. Desktop bekommt keinen Hinweis (Chrome/Edge zeigen dort selbst ein Symbol). */
export function installPlatform(userAgent: string, maxTouchPoints: number): InstallPlatform {
  if (/iPhone|iPad|iPod/i.test(userAgent) || (/Macintosh/i.test(userAgent) && maxTouchPoints > 1)) return "ios";
  if (/Android/i.test(userAgent)) return "android";
  return null;
}

export const INSTALL_DISMISS_KEY = "hocx-install-prompt-dismissed";
/** Nach «Schliessen» erst nach dieser Zeit wieder vorschlagen. */
export const INSTALL_DISMISS_MS = 30 * 24 * 60 * 60 * 1000;

export function dismissedRecently(stored: string | null, now: number): boolean {
  const at = Number(stored);
  return Number.isFinite(at) && at > 0 && now - at < INSTALL_DISMISS_MS;
}

/** Das Ereignis, mit dem Chrome/Edge/Samsung Internet die Installation anbieten. */
export type BeforeInstallPromptEvent = Event & {
  prompt: () => Promise<void>;
  userChoice: Promise<{ outcome: "accepted" | "dismissed" }>;
};

// Das Ereignis kann vor dem ersten Rendern kommen: schon beim Laden des Moduls mithören.
let deferred: BeforeInstallPromptEvent | null = null;
const listeners = new Set<() => void>();

if (typeof window !== "undefined") {
  window.addEventListener("beforeinstallprompt", (event) => {
    event.preventDefault();
    deferred = event as BeforeInstallPromptEvent;
    listeners.forEach((listener) => listener());
  });
  window.addEventListener("appinstalled", () => {
    deferred = null;
    listeners.forEach((listener) => listener());
  });
}

export function deferredInstallPrompt(): BeforeInstallPromptEvent | null {
  return deferred;
}

export function clearDeferredInstallPrompt(): void {
  deferred = null;
}

export function onInstallPromptChange(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function isStandalone(): boolean {
  if (typeof window === "undefined") return false;
  const nav = window.navigator as Navigator & { standalone?: boolean };
  return window.matchMedia?.("(display-mode: standalone)").matches === true || nav.standalone === true;
}
