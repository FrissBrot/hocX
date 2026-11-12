"use client";

import { FormEvent, useState } from "react";
import { useTranslations } from "next-intl";

import { useToast } from "@/contexts/toast-context";
import { browserApiFetch } from "@/lib/api/client";
import { apiErrorMessage } from "@/lib/api/error-message";

// Wie UserPasswordChange.new_password im Backend (backend/app/schemas/user.py).
export const MIN_PASSWORD_LENGTH = 12;

/** Grund, warum «Passwort ändern» gesperrt ist (Schlüssel unter security.passwordChange.reasons), oder null. */
export function passwordChangeBlocker(current: string, next: string, repeat: string): "current" | "tooShort" | "mismatch" | null {
  if (!current) return "current";
  if (next.length < MIN_PASSWORD_LENGTH) return "tooShort";
  if (next !== repeat) return "mismatch";
  return null;
}

/**
 * Eigenes Passwort ändern (POST /api/users/me/password). Das Backend beendet dabei alle anderen
 * Sitzungen und stellt der aktuellen ein neues Cookie aus; per E-Mail kommt ein Sicherheitshinweis.
 */
export function PasswordChangePanel() {
  const t = useTranslations("security.passwordChange");
  const tSecurity = useTranslations("security");
  const showToast = useToast();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [repeat, setRepeat] = useState("");
  const [busy, setBusy] = useState(false);
  const blocker = passwordChangeBlocker(current, next, repeat);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (blocker || busy) return;
    setBusy(true);
    try {
      await browserApiFetch("/api/users/me/password", {
        method: "POST",
        body: JSON.stringify({ current_password: current, new_password: next }),
      });
      setCurrent("");
      setNext("");
      setRepeat("");
      showToast(t("success"), "success");
    } catch (error) {
      showToast(apiErrorMessage(error, tSecurity, "apiErrors", t("failed")), "error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="grid" onSubmit={(event) => void submit(event)}>
      <div>
        <h3>{t("title")}</h3>
        <p className="muted">{t("description")}</p>
      </div>
      <label className="field-stack">
        <span className="field-label">{t("current")}</span>
        <input type="password" autoComplete="current-password" value={current} onChange={(event) => setCurrent(event.target.value)} />
      </label>
      <div className="two-col">
        <label className="field-stack">
          <span className="field-label">{t("new")}</span>
          <input type="password" autoComplete="new-password" value={next} onChange={(event) => setNext(event.target.value)} />
          <span className="field-help">{t("newHelp", { count: MIN_PASSWORD_LENGTH })}</span>
        </label>
        <label className="field-stack">
          <span className="field-label">{t("repeat")}</span>
          <input type="password" autoComplete="new-password" value={repeat} onChange={(event) => setRepeat(event.target.value)} />
        </label>
      </div>
      <div className="table-actions table-actions-start">
        <button type="submit" className="button-secondary" disabled={Boolean(blocker) || busy}>
          {busy ? t("saving") : t("submit")}
        </button>
        {blocker && (current || next || repeat) ? <span className="field-help">{t(`reasons.${blocker}`, { count: MIN_PASSWORD_LENGTH })}</span> : null}
      </div>
    </form>
  );
}
