"use client";

// Aktionen zu einem Mandanten (Klonen, Export, Löschen) - gemeinsam genutzt von der Mandantenliste
// und der Detailseite /admin/tenants/[id] (Admin-Redesign §5.2). Herausgelöst aus
// admin-tenant-management.tsx, Verhalten unverändert (Step-up über stepUpFetch/stepUpHeaders).

import { FormEvent, useEffect, useState } from "react";
import { useTranslations } from "next-intl";

import { Modal } from "@/components/ui/modal";
import { useConfirm } from "@/contexts/confirm-context";
import { useToast } from "@/contexts/toast-context";
import { stepUpFetch, stepUpHeaders } from "@/lib/admin-step-up";
import { LONG_RUNNING_TIMEOUT_MS } from "@/lib/api/client";
import { AdminTenantSummary } from "@/types/api";

// Wie export_crypto.MIN_PASSWORD_LENGTH im Backend.
export const EXPORT_PASSWORD_MIN_LENGTH = 12;

type ExportScope = "structure" | "structure_lists" | "full" | "full_abgabebox";

export function TenantCloneModal({
  tenant,
  onClose,
  onCloned,
}: {
  tenant: AdminTenantSummary | null;
  onClose: () => void;
  onCloned: (clone: AdminTenantSummary) => void | Promise<void>;
}) {
  const t = useTranslations("admin.tenants");
  const showToast = useToast();
  const [cloneName, setCloneName] = useState("");
  const [cloneMode, setCloneMode] = useState<"structure" | "full">("structure");
  const [cloneBusy, setCloneBusy] = useState(false);

  useEffect(() => {
    if (!tenant) return;
    setCloneName(t("cloneDefaultName", { name: tenant.name }));
    setCloneMode("structure");
  }, [tenant, t]);

  async function submitClone(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!tenant) return;
    setCloneBusy(true);
    try {
      const clone = await stepUpFetch<AdminTenantSummary>("tenant-export", `/api/admin/tenants/${tenant.id}/clone`, {
        method: "POST",
        body: JSON.stringify({ new_name: cloneName, mode: cloneMode }),
        timeoutMs: LONG_RUNNING_TIMEOUT_MS,
      });
      await onCloned(clone);
      onClose();
      showToast(t("cloned"), "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("cloneFailed"), "error");
    } finally {
      setCloneBusy(false);
    }
  }

  return (
    <Modal
      open={tenant !== null}
      onClose={onClose}
      title={tenant ? t("cloneTitleNamed", { name: tenant.name }) : t("cloneTitle")}
      description={t("cloneDescription")}
    >
      <form className="grid" onSubmit={submitClone}>
        <label className="field-stack">
          <span className="field-label">{t("nameOfNewTenant")}</span>
          <input value={cloneName} onChange={(event) => setCloneName(event.target.value)} required />
        </label>
        <div className="field-stack">
          <span className="field-label">{t("scope")}</span>
          <label className="field-radio-option">
            <input type="radio" name="clone-mode" value="structure" checked={cloneMode === "structure"} onChange={() => setCloneMode("structure")} />
            <span>
              <strong>{t("cloneStructureOnlyTitle")}</strong>
              <div className="muted">{t("cloneStructureOnlyDescription")}</div>
            </span>
          </label>
          <label className="field-radio-option">
            <input type="radio" name="clone-mode" value="full" checked={cloneMode === "full"} onChange={() => setCloneMode("full")} />
            <span>
              <strong>{t("cloneFullTitle")}</strong>
              <div className="muted">{t("cloneFullDescription")}</div>
            </span>
          </label>
        </div>
        <div className="modal-actions">
          <button type="button" className="button-ghost" onClick={onClose}>
            {t("cancel")}
          </button>
          <button type="submit" className="button-primary" disabled={cloneBusy}>
            {cloneBusy ? t("cloning") : t("clone")}
          </button>
        </div>
      </form>
    </Modal>
  );
}

export function TenantExportModal({ tenant, onClose }: { tenant: AdminTenantSummary | null; onClose: () => void }) {
  const t = useTranslations("admin.tenants");
  const showToast = useToast();
  const [exportScope, setExportScope] = useState<ExportScope>("structure");
  const [exportPassword, setExportPassword] = useState("");
  const [exportPasswordConfirm, setExportPasswordConfirm] = useState("");
  const [exportCredentials, setExportCredentials] = useState(false);

  useEffect(() => {
    if (!tenant) return;
    setExportScope("structure");
    setExportPassword("");
    setExportPasswordConfirm("");
  }, [tenant]);

  // Ohne Passwort verschlüsselt das Backend mit dem Server-Schlüssel (export_crypto.py); mit
  // Passwort muss es lang genug und bestätigt sein.
  const exportPasswordTooShort = exportPassword !== "" && exportPassword.length < EXPORT_PASSWORD_MIN_LENGTH;
  const exportPasswordMismatch = exportPassword !== "" && exportPassword !== exportPasswordConfirm;

  async function submitExport(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!tenant) return;
    // POST statt GET-Link (Audit 2026-08-25): nur per JS vom eigenen Origin auslösbar, Download als Blob.
    try {
      const { browserApiBaseUrl } = await import("@/lib/api/client");
      // Das optionale Passwort steht nur im Body, nie in einer URL.
      const exportPath = `/api/admin/tenants/${tenant.id}/export`;
      const exportBody = JSON.stringify({ scope: exportScope, password: exportPassword || null, include_credentials: exportCredentials });
      // Export enthält alle Daten des Mandanten: nur mit Passkey-Bestätigung (Security-Review M2)
      const confirmHeaders = await stepUpHeaders("tenant-export", "POST", exportPath, exportBody);
      const res = await fetch(`${browserApiBaseUrl}${exportPath}`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json", ...confirmHeaders },
        body: exportBody,
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const blob = await res.blob();
      const disposition = res.headers.get("content-disposition") ?? "";
      const filenameMatch = /filename="?([^";]+)"?/i.exec(disposition);
      const filename = filenameMatch?.[1] ?? `${tenant.name}-export.zip.hocxenc`;
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      a.click();
      URL.revokeObjectURL(url);
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("exportFailed"), "error");
      return;
    }
    onClose();
  }

  const scopes: { value: ExportScope; title: string; description: string }[] = [
    { value: "structure", title: t("exportStructureOnlyTitle"), description: t("exportStructureOnlyDescription") },
    { value: "structure_lists", title: t("exportStructureListsTitle"), description: t("exportStructureListsDescription") },
    { value: "full", title: t("exportFullTitle"), description: t("exportFullDescription") },
    { value: "full_abgabebox", title: t("exportFullAbgabeboxTitle"), description: t("exportFullAbgabeboxDescription") },
  ];

  return (
    <Modal
      open={tenant !== null}
      onClose={onClose}
      title={tenant ? t("exportTitleNamed", { name: tenant.name }) : t("exportTitle")}
      description={t("exportDescription")}
    >
      <form className="grid" onSubmit={submitExport}>
        <div className="field-stack">
          <span className="field-label">{t("scope")}</span>
          {scopes.map((scope) => (
            <label key={scope.value} className="field-radio-option">
              <input type="radio" name="export-scope" value={scope.value} checked={exportScope === scope.value} onChange={() => setExportScope(scope.value)} />
              <span>
                <strong>{scope.title}</strong>
                <div className="muted">{scope.description}</div>
              </span>
            </label>
          ))}
        </div>
        {/* Datenschutz-Audit Paket 6: Zugangsdaten nur auf ausdrücklichen Wunsch */}
        <label className="checkbox-row"><input type="checkbox" checked={exportCredentials} onChange={(event) => setExportCredentials(event.target.checked)} /><span>{t("exportCredentials")}</span></label>
        <p className="field-help">{t("exportCredentialsHint")}</p>
        <label className="field-stack">
          <span className="field-label">{t("exportPasswordLabel")}</span>
          <input type="password" autoComplete="new-password" value={exportPassword} onChange={(event) => setExportPassword(event.target.value)} />
          <span className="field-help">
            {exportPasswordTooShort ? t("exportPasswordTooShort", { min: EXPORT_PASSWORD_MIN_LENGTH }) : t("exportPasswordHelp")}
          </span>
        </label>
        {exportPassword ? (
          <label className="field-stack">
            <span className="field-label">{t("exportPasswordConfirmLabel")}</span>
            <input type="password" autoComplete="new-password" value={exportPasswordConfirm} onChange={(event) => setExportPasswordConfirm(event.target.value)} />
            {exportPasswordConfirm && exportPasswordMismatch ? <span className="field-help">{t("exportPasswordMismatch")}</span> : null}
          </label>
        ) : null}
        <div className="modal-actions">
          <button type="button" className="button-ghost" onClick={onClose}>
            {t("cancel")}
          </button>
          <button type="submit" className="button-primary" disabled={exportPasswordTooShort || exportPasswordMismatch}>
            {t("export")}
          </button>
        </div>
      </form>
    </Modal>
  );
}

/** Löschen mit Rückfrage und Passkey-Bestätigung; liefert true, wenn der Mandant gelöscht wurde. */
export function useTenantDelete(): (tenant: AdminTenantSummary) => Promise<boolean> {
  const t = useTranslations("admin.tenants");
  const showToast = useToast();
  const confirm = useConfirm();
  return async (tenant) => {
    const confirmed = await confirm({
      title: t("deleteConfirmTitle", { name: tenant.name }),
      message: t("deleteConfirmMessage", { participants: tenant.participant_count, users: tenant.user_count }),
      tone: "danger",
      confirmLabel: t("deletePermanently"),
    });
    if (!confirmed) return false;
    try {
      await stepUpFetch("tenant-delete", `/api/admin/tenants/${tenant.id}`, { method: "DELETE" });
      showToast(t("deleted"), "success");
      return true;
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("deleteFailed"), "error");
      return false;
    }
  };
}
