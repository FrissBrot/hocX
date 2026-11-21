"use client";

import { FormEvent, useState } from "react";
import { useTranslations } from "next-intl";

import { EXPORT_PASSWORD_MIN_LENGTH } from "@/components/admin/tenant-detail/tenant-action-modals";
import { DateInput } from "@/components/ui/date-input";
import { Modal } from "@/components/ui/modal";
import { Select } from "@/components/ui/select";
import { useToast } from "@/contexts/toast-context";
import { stepUpDownload } from "@/lib/admin-step-up";

export type SecurityExportKind = "auth_events" | "audit_log";

// Wie backend admin_auth_security.EXPORT_MAX_DAYS
export const SECURITY_EXPORT_MAX_DAYS = 92;

function isoDay(date: Date): string {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}

export function daysBetween(from: string, to: string): number {
  return Math.round((Date.parse(`${to}T00:00:00Z`) - Date.parse(`${from}T00:00:00Z`)) / 86_400_000);
}

/** Export von Anmeldeereignissen bzw. Audit-Log als verschlüsselte JSONL-Datei (Passwort Pflicht,
 * Passkey-Bestätigung «security-export», auditiert). Das Passwort steht nur im Body. */
export function SecurityExportButton({ kind: initialKind }: { kind: SecurityExportKind }) {
  const t = useTranslations("adminSecurity.export");
  const showToast = useToast();
  const [open, setOpen] = useState(false);
  const [kind, setKind] = useState<SecurityExportKind>(initialKind);
  const today = new Date();
  const [from, setFrom] = useState(() => isoDay(new Date(today.getTime() - 7 * 86_400_000)));
  const [to, setTo] = useState(() => isoDay(today));
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [busy, setBusy] = useState(false);

  const span = from && to ? daysBetween(from, to) : -1;
  const rangeInvalid = !from || !to || span < 0 || span >= SECURITY_EXPORT_MAX_DAYS;
  const passwordTooShort = password.length < EXPORT_PASSWORD_MIN_LENGTH;
  const mismatch = password !== confirmPassword;
  const valid = !rangeInvalid && !passwordTooShort && !mismatch;

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!valid) return;
    setBusy(true);
    try {
      const body = JSON.stringify({ kind, date_from: from, date_to: to, password });
      await stepUpDownload("security-export", "/api/admin/auth-security/export", body, `hocx-${kind}.jsonl.hocxenc`);
      showToast(t("done"), "success");
      setPassword("");
      setConfirmPassword("");
      setOpen(false);
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("failed"), "error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <button type="button" className="button-secondary" onClick={() => setOpen(true)}>
        {t("button")}
      </button>
      <Modal open={open} onClose={() => setOpen(false)} title={t("title")} description={t("description")}>
        <form className="grid" onSubmit={submit}>
          <label className="field-stack">
            <span className="field-label">{t("kind")}</span>
            <Select value={kind} onChange={(event) => setKind(event.target.value as SecurityExportKind)}>
              <option value="auth_events">{t("kinds.auth_events")}</option>
              <option value="audit_log">{t("kinds.audit_log")}</option>
            </Select>
          </label>
          <div className="two-col">
            <label className="field-stack">
              <span className="field-label">{t("from")}</span>
              <DateInput value={from} max={to || undefined} onChange={setFrom} />
            </label>
            <label className="field-stack">
              <span className="field-label">{t("to")}</span>
              <DateInput value={to} min={from || undefined} onChange={setTo} />
            </label>
          </div>
          {rangeInvalid ? <span className="field-help">{t("rangeHelp", { days: SECURITY_EXPORT_MAX_DAYS })}</span> : null}
          <div className="two-col">
            <label className="field-stack">
              <span className="field-label">{t("password")}</span>
              <input type="password" autoComplete="new-password" value={password} onChange={(event) => setPassword(event.target.value)} />
              <span className="field-help">{t("passwordHelp", { min: EXPORT_PASSWORD_MIN_LENGTH })}</span>
            </label>
            <label className="field-stack">
              <span className="field-label">{t("passwordConfirm")}</span>
              <input type="password" autoComplete="new-password" value={confirmPassword} onChange={(event) => setConfirmPassword(event.target.value)} />
              {confirmPassword && mismatch ? <span className="field-help">{t("mismatch")}</span> : null}
            </label>
          </div>
          <div className="modal-actions">
            <button type="button" className="button-ghost" onClick={() => setOpen(false)}>
              {t("cancel")}
            </button>
            <button type="submit" className="button-primary" disabled={!valid || busy}>
              {busy ? t("busy") : t("submit")}
            </button>
          </div>
        </form>
      </Modal>
    </>
  );
}
