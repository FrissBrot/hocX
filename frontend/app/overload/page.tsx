"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";

import { CopyrightNotice } from "@/components/ui/copyright-notice";
import { safeReturnPath } from "@/lib/api/client";

// Das Backend schickt Retry-After: 60 - halb so oft nachfragen, damit niemand länger als nötig wartet.
const RETRY_MS = 30_000;

/** Überlast-Ansicht (Weiterleitung aus proxy.ts bzw. bei einer 503-Antwort mit Code "overloaded").
 * Neue Nutzer von Abos mit niedriger Priorität warten hier, bis das Backend wieder Platz hat
 * (app/core/db_admission.py), und kehren dann automatisch zur ursprünglichen Seite zurück. */
export default function OverloadPage() {
  const t = useTranslations("overload");
  const router = useRouter();
  const [checking, setChecking] = useState(false);

  const check = useCallback(async () => {
    setChecking(true);
    try {
      const response = await fetch("/api/auth/session", { cache: "no-store", credentials: "include" });
      if (response.ok) {
        // Ohne useSearchParams: die Seite bleibt statisch vorrenderbar (keine Suspense-Grenze nötig).
        const target = safeReturnPath(new URLSearchParams(window.location.search).get("from"));
        router.replace(target as Parameters<typeof router.replace>[0]);
        return;
      }
    } catch {
      // Netzwerkfehler: beim nächsten Versuch erneut prüfen.
    }
    setChecking(false);
  }, [router]);

  useEffect(() => {
    const timer = setInterval(() => void check(), RETRY_MS);
    return () => clearInterval(timer);
  }, [check]);

  return (
    <main className="login-frame">
      <section className="login-panel">
        <div className="login-brand">
          <div className="login-avatar login-avatar-fallback">
            <span>hX</span>
          </div>
          <div className="eyebrow">hocX</div>
        </div>
        <div className="maintenance-notice" role="status" aria-live="polite">
          <h1 className="maintenance-notice-title">{t("title")}</h1>
          <p>{t("message")}</p>
          <p className="muted">{t("hint")}</p>
        </div>
        <button type="button" className="button-secondary" onClick={() => void check()} disabled={checking}>
          {checking ? t("checking") : t("retry")}
        </button>
      </section>
      <CopyrightNotice className="login-copyright" />
    </main>
  );
}
