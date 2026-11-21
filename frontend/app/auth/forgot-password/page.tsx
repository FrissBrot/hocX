"use client";

import { FormEvent, useEffect, useState } from "react";
import { useTranslations } from "next-intl";

import { StatusBanner } from "@/components/ui/status-banner";
import { browserApiFetch } from "@/lib/api/client";

/**
 * «Passwort vergessen» (Benachrichtigungen Phase 3): fordert einen Einmal-Link per E-Mail an.
 * Die Antwort ist immer dieselbe, ob es das Konto gibt oder nicht - deshalb zeigt die Seite nach
 * dem Absenden immer denselben Hinweis. Ist der E-Mail-Versand gestört (plattformweiter Zustand,
 * unabhängig vom Konto - kein Orakel), steht ein Hinweis darüber.
 */
export default function ForgotPasswordPage() {
  const t = useTranslations("auth.forgotPassword");
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState(false);
  const [error, setError] = useState("");
  const [mailDisturbed, setMailDisturbed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    browserApiFetch<{ enabled: boolean; disturbed?: boolean }>("/api/auth/password-reset/available")
      .then((result) => { if (!cancelled) setMailDisturbed(Boolean(result?.disturbed)); })
      .catch(() => undefined);
    return () => { cancelled = true; };
  }, []);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await browserApiFetch("/api/auth/password-reset/request", { method: "POST", body: JSON.stringify({ email: email.trim() }) });
      setSent(true);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : t("failed"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="login-frame">
      <section className="login-panel">
        <div className="login-heading">
          <h1>{t("title")}</h1>
          <p className="login-subtitle">{sent ? t("sent") : t("intro")}</p>
        </div>
        {mailDisturbed ? <StatusBanner tone="warning" message={t("mailDisturbed")} /> : null}
        {sent ? (
          <div className="table-actions table-actions-start">
            <a className="button-primary" href="/login">{t("toLogin")}</a>
          </div>
        ) : (
          <form className="account-link-form" onSubmit={(event) => void submit(event)}>
            <label className="field-stack">
              <span className="field-label">{t("emailLabel")}</span>
              <input className="input" type="email" value={email} onChange={(event) => setEmail(event.target.value)} required autoComplete="email" />
            </label>
            <div className="table-actions table-actions-start">
              <a className="button-ghost" href="/login">{t("cancel")}</a>
              <button type="submit" className="button-primary" disabled={busy || !email.trim()}>{busy ? "…" : t("submit")}</button>
            </div>
            {error ? <p className="login-status">{error}</p> : null}
          </form>
        )}
      </section>
    </main>
  );
}
