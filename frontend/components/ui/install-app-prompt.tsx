"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { usePathname } from "next/navigation";

import {
  clearDeferredInstallPrompt,
  deferredInstallPrompt,
  dismissedRecently,
  INSTALL_DISMISS_KEY,
  installPlatform,
  isStandalone,
  onInstallPromptChange,
  type InstallPlatform,
} from "@/lib/pwa/install";

function readDismissed(): string | null {
  try {
    return window.localStorage.getItem(INSTALL_DISMISS_KEY);
  } catch {
    return null;
  }
}

function ShareGlyph() {
  // iOS-Teilen-Symbol (Quadrat mit Pfeil nach oben), damit man den Knopf in Safari wiedererkennt
  return (
    <svg className="install-app-share" viewBox="0 0 16 16" aria-hidden="true" focusable="false">
      <path d="M8 1.5v8M5 4.5l3-3 3 3" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M5.5 7H4a1 1 0 0 0-1 1v5.5a1 1 0 0 0 1 1h8a1 1 0 0 0 1-1V8a1 1 0 0 0-1-1h-1.5" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  );
}

/** Schlägt auf iPhone/iPad und Android vor, hocX als App zu installieren (PWA, ohne App Store).
 * Android: echter Installationsdialog des Browsers (beforeinstallprompt), sonst Anleitung über
 * das Browsermenü. iOS: Anleitung «Teilen → Zum Home-Bildschirm» (Safari bietet keinen Dialog).
 * Nicht in der installierten App selbst; «Schliessen» blendet ihn für 30 Tage aus. */
export function InstallAppPrompt() {
  const t = useTranslations("common.installApp");
  const [platform, setPlatform] = useState<InstallPlatform>(null);
  const [canPrompt, setCanPrompt] = useState(false);
  const [hidden, setHidden] = useState(true);
  // Nicht beim Schreiben im Protokoll-Editor
  const inEditor = /^\/protocols\/[^/]+/.test(usePathname() ?? "");

  useEffect(() => {
    const detected = installPlatform(window.navigator.userAgent, window.navigator.maxTouchPoints ?? 0);
    if (!detected || isStandalone() || dismissedRecently(readDismissed(), Date.now())) return;
    setPlatform(detected);
    setHidden(false);
    const update = () => setCanPrompt(deferredInstallPrompt() !== null);
    update();
    return onInstallPromptChange(update);
  }, []);

  if (hidden || !platform || inEditor) return null;

  function dismiss() {
    try {
      window.localStorage.setItem(INSTALL_DISMISS_KEY, String(Date.now()));
    } catch {
      // ohne Speicher erscheint der Hinweis beim nächsten Laden wieder
    }
    setHidden(true);
  }

  async function install() {
    const event = deferredInstallPrompt();
    if (!event) return;
    await event.prompt();
    const choice = await event.userChoice;
    clearDeferredInstallPrompt();
    setCanPrompt(false);
    if (choice.outcome === "accepted") setHidden(true);
  }

  return (
    <section className="install-app-prompt" aria-label={t("title")}>
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img className="install-app-icon" src="/icons/apple-touch-icon.png" alt="" width={40} height={40} />
      <div className="install-app-text">
        <strong>{t("title")}</strong>
        <span className="muted">
          {platform === "ios"
            ? t.rich("ios", { share: () => <ShareGlyph /> })
            : canPrompt
              ? t("android")
              : t("androidManual")}
        </span>
      </div>
      <div className="install-app-actions">
        {platform === "android" && canPrompt ? (
          <button type="button" className="button-primary" onClick={() => void install()}>
            {t("install")}
          </button>
        ) : null}
        <button type="button" className="button-icon-soft" aria-label={t("dismiss")} title={t("dismiss")} onClick={dismiss}>
          ✕
        </button>
      </div>
    </section>
  );
}
