"use client";

import { FormEvent, useEffect, useState } from "react";
import { useTranslations } from "next-intl";

import { FilterTabs } from "@/components/ui/filter-tabs";
import { Modal } from "@/components/ui/modal";
import { StatusBanner } from "@/components/ui/status-banner";
import { browserApiFetch } from "@/lib/api/client";
import { apiErrorMessage } from "@/lib/api/error-message";
import { browserSupportsPasskeys, getPasskeyAssertion } from "@/lib/webauthn";
import type { StepUpMethod, StepUpOptions } from "@/types/api";

type Props = {
  open: boolean;
  /** true: bestätigt, die Aktion wird wiederholt; false: abgebrochen */
  onDone: (confirmed: boolean) => void;
};

/**
 * Frische Anmeldung für kritische Aktionen (Step-up, Auth-Audit 2026-11-20 SEC-AUTH-010): zweiter
 * Faktor (Code oder Passkey) bzw. Passwort für Konten ohne Faktor. Wird von StepUpProvider
 * geöffnet, sobald das Backend 403 step_up_required meldet.
 */
export function StepUpDialog({ open, onDone }: Props) {
  const t = useTranslations("security.stepUp");
  const tSecurity = useTranslations("security");
  const [methods, setMethods] = useState<StepUpMethod[]>([]);
  const [method, setMethod] = useState<StepUpMethod | null>(null);
  // Optionen geladen (sonst ist eine leere Methodenliste von «lädt noch» nicht zu unterscheiden)
  const [loaded, setLoaded] = useState(false);
  const [code, setCode] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setCode("");
    setPassword("");
    setError("");
    setLoaded(false);
    browserApiFetch<StepUpOptions>("/api/auth/step-up", { skipStepUp: true })
      .then((options) => {
        if (cancelled) return;
        const usable = options.methods.filter((item) => item !== "passkey" || browserSupportsPasskeys());
        setMethods(usable);
        setMethod(usable[0] ?? null);
        setLoaded(true);
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(apiErrorMessage(err, tSecurity, "apiErrors", t("loadFailed")));
      });
    return () => {
      cancelled = true;
    };
    // Nur beim Öffnen laden: t/tSecurity sind je nach Umgebung nicht referenzstabil und würden
    // die Eingaben bei jedem Rendern zurücksetzen.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  async function confirm(body: Record<string, unknown>) {
    setBusy(true);
    setError("");
    try {
      await browserApiFetch("/api/auth/step-up", { method: "POST", body: JSON.stringify(body), skipStepUp: true });
      onDone(true);
    } catch (err) {
      setError(apiErrorMessage(err, tSecurity, "apiErrors", t("failed")));
    } finally {
      setBusy(false);
    }
  }

  async function confirmPasskey() {
    setBusy(true);
    setError("");
    try {
      const start = await browserApiFetch<{ flow_token: string; public_key: Record<string, unknown> }>("/api/auth/step-up/passkey/start", {
        method: "POST",
        skipStepUp: true,
      });
      const credential = await getPasskeyAssertion(start.public_key);
      await confirm({ method: "passkey", flow_token: start.flow_token, credential });
    } catch (err) {
      setError(apiErrorMessage(err, tSecurity, "apiErrors", t("failed")));
      setBusy(false);
    }
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (method === "totp") void confirm({ method: "totp", code });
    else if (method === "password") void confirm({ method: "password", password });
    else if (method === "passkey") void confirmPasskey();
  }

  const ready = method === "passkey" || (method === "totp" && /^\d{6}$/.test(code)) || (method === "password" && password.length > 0);

  return (
    <Modal open={open} title={t("title")} onClose={() => onDone(false)}>
      <form className="grid" onSubmit={submit}>
        <p className="muted">{t("description")}</p>
        {methods.length > 1 && method ? (
          <FilterTabs
            options={methods.map((item) => ({ value: item, label: t(`methods.${item}`) }))}
            value={method}
            onChange={(value) => setMethod(value)}
          />
        ) : null}
        {method === "totp" ? (
          <label className="field-stack">
            <span className="field-label">{t("codeLabel")}</span>
            <input
              inputMode="numeric"
              autoComplete="one-time-code"
              maxLength={6}
              value={code}
              onChange={(event) => setCode(event.target.value.replace(/\D/g, "").slice(0, 6))}
              autoFocus
            />
          </label>
        ) : null}
        {method === "password" ? (
          <label className="field-stack">
            <span className="field-label">{t("passwordLabel")}</span>
            <input type="password" autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} autoFocus />
          </label>
        ) : null}
        {method === "passkey" ? <p className="field-help">{t("passkeyHint")}</p> : null}
        {!method && !error && !loaded ? <p className="field-help">{t("loading")}</p> : null}
        {/* Nur Passkey, der hier nicht geht (Vereins-Domain, Browser ohne Passkeys): Ausweg nennen statt endlos zu laden */}
        {!method && !error && loaded ? <StatusBanner tone="warning" message={t("noMethod")} /> : null}
        {error ? <StatusBanner tone="error" message={error} /> : null}
        <div className="modal-actions">
          <button type="button" className="button-ghost" onClick={() => onDone(false)} disabled={busy}>
            {t("cancel")}
          </button>
          <button type="submit" className="button-primary" disabled={!ready || busy}>
            {busy ? t("checking") : t("confirm")}
          </button>
        </div>
      </form>
    </Modal>
  );
}
