"use client";

import { FormEvent, useState } from "react";
import { useTranslations } from "next-intl";

import { Modal } from "@/components/ui/modal";
import { useToast } from "@/contexts/toast-context";
import { postAndDownload } from "@/lib/download";

const MIN_PASSWORD_LENGTH = 12;

type FormProps = {
  path: string;
  fallbackFilename: string;
  extraBody?: Record<string, unknown>;
  submitLabel?: string;
  onDone?: () => void;
  onCancel?: () => void;
};

type Props = FormProps & {
  open: boolean;
  title: string;
  description: string;
  onClose: () => void;
};

// Passwort für einen verschlüsselten Export (AES-ZIP, Datenschutz-Audit Paket 5/6) abfragen und die
// Datei herunterladen. Das Passwort geht nur im Body an den Server und wird dort nicht gespeichert.
export function ProtectedExportModal({ open, title, description, onClose, onDone, ...form }: Props) {
  return (
    <Modal open={open} title={title} description={description} onClose={onClose}>
      <ProtectedExportForm {...form} onCancel={onClose} onDone={() => { onDone?.(); onClose(); }} />
    </Modal>
  );
}

// Formular ohne Modal, z. B. eingebettet im Profil (kein Modal im Modal).
export function ProtectedExportForm({ path, fallbackFilename, extraBody, submitLabel, onDone, onCancel }: FormProps) {
  const t = useTranslations("common.protectedExport");
  const showToast = useToast();
  const [password, setPassword] = useState("");
  const [repeat, setRepeat] = useState("");
  const [busy, setBusy] = useState(false);
  const valid = password.length >= MIN_PASSWORD_LENGTH && password === repeat;

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!valid) return;
    setBusy(true);
    try {
      await postAndDownload(path, { ...(extraBody ?? {}), password }, fallbackFilename);
      showToast(t("done"), "success");
      setPassword("");
      setRepeat("");
      onDone?.();
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("failed"), "error");
    } finally {
      setBusy(false);
    }
  }

  return (
      <form className="grid" onSubmit={(event) => void submit(event)}>
        <label className="field-stack">
          <span className="field-label">{t("password")}</span>
          <input type="password" autoComplete="new-password" value={password} onChange={(event) => setPassword(event.target.value)} />
          <span className="field-help">{t("passwordHelp", { min: MIN_PASSWORD_LENGTH })}</span>
        </label>
        <label className="field-stack">
          <span className="field-label">{t("repeat")}</span>
          <input type="password" autoComplete="new-password" value={repeat} onChange={(event) => setRepeat(event.target.value)} />
          {repeat && password !== repeat ? <span className="field-help">{t("mismatch")}</span> : null}
        </label>
        <p className="field-help">{t("openHint")}</p>
        <div className="modal-actions">
          {onCancel ? (
            <button type="button" className="button-ghost" onClick={onCancel} disabled={busy}>
              {t("cancel")}
            </button>
          ) : null}
          <button type="submit" className="button-primary" disabled={!valid || busy}>
            {busy ? t("working") : submitLabel ?? t("download")}
          </button>
        </div>
      </form>
  );
}
