"use client";

import { ChangeEvent, useMemo, useState } from "react";
import { useTranslations } from "next-intl";

import { Badge } from "@/components/ui/badge";
import { DataTable } from "@/components/ui/data-table";
import { Modal } from "@/components/ui/modal";
import { StatusBanner } from "@/components/ui/status-banner";
import { useConfirm } from "@/contexts/confirm-context";
import { useToast } from "@/contexts/toast-context";
import { ApiError, browserApiFetch } from "@/lib/api/client";
import { CatalogImportChange, CatalogImportPreview, CatalogImportRequest } from "@/types/api";

const ACTION_VARIANTS = {
  create: "success",
  update: "info",
  deactivate: "warning",
  delete: "danger",
} as const;

const ACTIONS = ["create", "update", "deactivate", "delete"] as const;

// Werte aus der JSON-Datei 1:1 anzeigen (Feldnamen und Einheiten wie in der Datei).
function formatValue(value: unknown): string {
  if (value === null || value === undefined) return "–";
  if (Array.isArray(value)) return value.length === 0 ? "[]" : value.join(", ");
  if (typeof value === "string") return value;
  return JSON.stringify(value);
}

/** Lädt den Preiskatalog vom Server als JSON-Datei (inkl. Anleitung) herunter. */
export async function downloadCatalogConfig() {
  const config = await browserApiFetch<Record<string, unknown>>("/api/admin/catalog/export");
  const blob = new Blob([JSON.stringify(config, null, 2) + "\n"], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `hocx-preiskatalog-${new Date().toISOString().slice(0, 10)}.json`; // i18n-ok: Dateiname
  a.click();
  URL.revokeObjectURL(url);
}

type Props = {
  open: boolean;
  onClose: () => void;
  onImported: () => void;
};

export function AdminCatalogImportModal({ open, onClose, onImported }: Props) {
  const t = useTranslations("admin.catalogImport");
  const showToast = useToast();
  const confirm = useConfirm();
  const [fileName, setFileName] = useState("");
  const [config, setConfig] = useState<Record<string, unknown> | null>(null);
  const [parseError, setParseError] = useState<string | null>(null);
  const [overwrite, setOverwrite] = useState(false);
  const [preview, setPreview] = useState<CatalogImportPreview | null>(null);
  const [busy, setBusy] = useState(false);

  const counts = useMemo(() => {
    const result = { create: 0, update: 0, deactivate: 0, delete: 0 };
    for (const change of preview?.changes ?? []) result[change.action] += 1;
    return result;
  }, [preview]);

  function reset() {
    setFileName("");
    setConfig(null);
    setParseError(null);
    setOverwrite(false);
    setPreview(null);
  }

  function close() {
    if (busy) return;
    reset();
    onClose();
  }

  async function selectFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    setPreview(null);
    setConfig(null);
    setParseError(null);
    setFileName(file?.name ?? "");
    if (!file) return;
    try {
      const parsed: unknown = JSON.parse(await file.text());
      if (parsed === null || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error("not an object");
      setConfig(parsed as Record<string, unknown>);
    } catch {
      setParseError(t("invalidJson"));
    }
  }

  function changeOverwrite(value: boolean) {
    setOverwrite(value);
    setPreview(null);
  }

  async function loadPreview() {
    if (!config) return;
    setBusy(true);
    try {
      const body: CatalogImportRequest = { config, overwrite };
      setPreview(await browserApiFetch<CatalogImportPreview>("/api/admin/catalog/import/preview", { method: "POST", body: JSON.stringify(body) }));
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("previewFailed"), "error");
    } finally {
      setBusy(false);
    }
  }

  async function applyImport() {
    if (!config || !preview) return;
    if (counts.delete > 0 || counts.deactivate > 0) {
      const confirmed = await confirm({
        title: t("confirmTitle"),
        message: t("confirmMessage", { deleted: counts.delete, deactivated: counts.deactivate }),
        tone: "danger",
        confirmLabel: t("apply"),
      });
      if (!confirmed) return;
    }
    setBusy(true);
    try {
      const body: CatalogImportRequest = { config, overwrite, base_fingerprint: preview.base_fingerprint };
      const result = await browserApiFetch<CatalogImportPreview>("/api/admin/catalog/import", { method: "POST", body: JSON.stringify(body) });
      showToast(t("applied", { count: result.changes.length }), "success");
      reset();
      onImported();
      onClose();
    } catch (error) {
      // 409: Katalog hat sich seit der Vorschau geändert - Vorschau verwerfen, damit sie neu geladen wird.
      if (error instanceof ApiError && error.status === 409) setPreview(null);
      showToast(error instanceof Error ? error.message : t("applyFailed"), "error");
    } finally {
      setBusy(false);
    }
  }

  const canApply = preview !== null && preview.errors.length === 0 && preview.changes.length > 0;

  return (
    <Modal open={open} onClose={close} title={t("title")} description={t("description")} size="wide">
      <div className="grid">
        <label className="field-stack">
          <span className="field-label">{t("file")}</span>
          <input type="file" accept=".json,application/json" onChange={(event) => void selectFile(event)} disabled={busy} />
          <span className="field-help">{fileName ? fileName : t("fileHelp")}</span>
        </label>
        {parseError ? <StatusBanner tone="error" message={parseError} /> : null}

        <div className="field-stack">
          <label className="admin-inline-check">
            <input type="checkbox" checked={overwrite} onChange={(event) => changeOverwrite(event.target.checked)} disabled={busy} />
            {t("overwrite")}
          </label>
          <span className="field-help">{overwrite ? t("overwriteHelp") : t("mergeHelp")}</span>
        </div>

        {preview ? (
          <section className="admin-form-section">
            <div className="admin-section-title">{t("previewTitle")}</div>
            {preview.errors.length > 0 ? (
              <div className="grid">
                <StatusBanner tone="error" message={t("errorsTitle", { count: preview.errors.length })} />
                <ul className="admin-catalog-errors">
                  {preview.errors.map((error) => (
                    <li key={error}>{error}</li>
                  ))}
                </ul>
              </div>
            ) : preview.changes.length === 0 ? (
              <StatusBanner tone="neutral" message={t("noChanges")} />
            ) : (
              <>
                <div className="admin-badge-row">
                  {ACTIONS.filter((action) => counts[action] > 0).map((action) => (
                    <Badge key={action} variant={ACTION_VARIANTS[action]}>
                      {t(`summary.${action}`, { count: counts[action] })}
                    </Badge>
                  ))}
                  <Badge variant="neutral">{t("summary.unchanged", { count: preview.unchanged_count })}</Badge>
                </div>
                <DataTable columns={[t("colEntry"), t("colAction"), t("colChanges")]} emptyMessage={t("noChanges")}>
                  {preview.changes.map((change) => (
                    <PreviewRow key={`${change.entity}:${change.code}`} change={change} />
                  ))}
                </DataTable>
              </>
            )}
          </section>
        ) : null}

        <div className="modal-actions">
          <button type="button" className="button-ghost" onClick={close} disabled={busy}>
            {t("cancel")}
          </button>
          {preview === null ? (
            <button type="button" className="button-primary" onClick={() => void loadPreview()} disabled={busy || !config}>
              {busy ? t("checking") : t("showPreview")}
            </button>
          ) : (
            <button type="button" className="button-primary" onClick={() => void applyImport()} disabled={busy || !canApply}>
              {busy ? t("applying") : t("apply")}
            </button>
          )}
        </div>
      </div>
    </Modal>
  );
}

function PreviewRow({ change }: { change: CatalogImportChange }) {
  const t = useTranslations("admin.catalogImport");
  return (
    <tr>
      <td>
        <strong>{change.name}</strong>
        <div className="muted admin-cell-sub">
          {t(`entity.${change.entity}`)} · <code>{change.code}</code>
        </div>
      </td>
      <td>
        <Badge variant={ACTION_VARIANTS[change.action]}>{t(`action.${change.action}`)}</Badge>
        {change.tenant_count > 0 && (change.action === "deactivate" || change.action === "update") ? (
          <div className="muted admin-cell-sub">{t("tenantCount", { count: change.tenant_count })}</div>
        ) : null}
      </td>
      <td>
        {change.action === "delete" ? (
          <span className="muted">–</span>
        ) : (
          <ul className="admin-catalog-change-list">
            {change.changes.map((fieldChange) => (
              <li key={fieldChange.field}>
                <code>{fieldChange.field}</code>{" "}
                {change.action === "create" ? (
                  formatValue(fieldChange.new)
                ) : (
                  <>
                    <span className="muted">{formatValue(fieldChange.old)}</span> → {formatValue(fieldChange.new)}
                  </>
                )}
              </li>
            ))}
          </ul>
        )}
      </td>
    </tr>
  );
}
