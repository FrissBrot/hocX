"use client";

import { useState } from "react";
import { useLocale, useTranslations } from "next-intl";

import { Badge } from "@/components/ui/badge";
import { DataTable } from "@/components/ui/data-table";
import { Modal, ModalSaveForm } from "@/components/ui/modal";
import { Select } from "@/components/ui/select";
import { StatusBanner } from "@/components/ui/status-banner";
import { useConfirm } from "@/contexts/confirm-context";
import { useToast } from "@/contexts/toast-context";
import { useAdminResource } from "@/components/admin/security/use-admin-resource";
import { stepUpFetch } from "@/lib/admin-step-up";
import { formatDateTime } from "@/lib/utils/format";
import type { AuthBlock } from "@/types/admin-security";

// Höchstdauer einer manuellen Sperre (backend app/auth_security/blocks.py::MAX_MANUAL_MINUTES)
const MAX_MINUTES = 30 * 24 * 60;

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

/** /admin/security/blocks: aktive Sperren; Setzen und Entsperren mit Passkey-Bestätigung
 * (Zweck security-block, gebunden an Methode, Pfad und Body - backend admin_step_up.py). */
export function SecurityBlocks({ canWrite }: { canWrite: boolean }) {
  const t = useTranslations("adminSecurity.blocks");
  const tRoot = useTranslations("adminSecurity");
  const locale = useLocale();
  const confirm = useConfirm();
  const showToast = useToast();
  const blocks = useAdminResource<AuthBlock[]>("/api/admin/auth-security/blocks");
  const [createOpen, setCreateOpen] = useState(false);
  const [ip, setIp] = useState("");
  const [scope, setScope] = useState<"source" | "net">("source");
  const [minutes, setMinutes] = useState("60");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);

  const minutesValue = Number.parseInt(minutes, 10);
  const minutesValid = Number.isInteger(minutesValue) && minutesValue > 0 && minutesValue <= MAX_MINUTES; // i18n-ok: Vergleich, kein UI-Text
  const formValid = ip.trim().length > 0 && reason.trim().length > 2 && minutesValid;

  async function unblock(block: AuthBlock) {
    const short = block.subject.slice(0, 12);
    const confirmed = await confirm({ message: t("unblockConfirm", { subject: short }), tone: "danger", confirmLabel: t("unblock") });
    if (!confirmed) return;
    const path = `/api/admin/auth-security/blocks/${encodeURIComponent(block.subject)}`;
    try {
      await stepUpFetch("security-block", path, { method: "DELETE" });
      showToast(t("unblocked"), "success");
      blocks.reload();
    } catch (error) {
      showToast(t("failed", { message: errorMessage(error) }), "error");
    }
  }

  async function create() {
    if (!formValid) return;
    setBusy(true);
    const body = JSON.stringify({ ip: ip.trim(), scope, minutes: minutesValue, reason: reason.trim() });
    try {
      await stepUpFetch("security-block", "/api/admin/auth-security/blocks", { method: "POST", body });
      showToast(t("created"), "success");
      setCreateOpen(false);
      setIp("");
      setReason("");
      blocks.reload();
    } catch (error) {
      showToast(t("failed", { message: errorMessage(error) }), "error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="card section-stack">
      {blocks.failed ? <StatusBanner tone="error" message={tRoot("loadFailed")} /> : null}
      {!canWrite ? <StatusBanner tone="neutral" message={t("readOnly")} /> : null}
      <div className="admin-security-toolbar">
        <button type="button" className="button-secondary" onClick={blocks.reload}>{tRoot("refresh")}</button>
        {canWrite ? (
          <button type="button" className="button-primary" onClick={() => setCreateOpen(true)}>{t("add")}</button>
        ) : null}
      </div>
      <DataTable
        columns={[t("columns.subject"), t("columns.scope"), t("columns.kind"), t("columns.stage"), t("columns.reason"), t("columns.until"), t("columns.actions")]}
        emptyMessage={blocks.loading ? undefined : t("empty")}
      >
        {(blocks.data ?? []).map((block) => (
          <tr key={block.subject}>
            <td><code>{block.subject.slice(0, 12)}</code></td>
            <td>{t(`scopes.${block.scope}`)}</td>
            <td><Badge variant={block.manual ? "info" : "warning"}>{block.manual ? t("manual") : t("automatic")}</Badge></td>
            <td>{block.stage}</td>
            <td>{block.reason}</td>
            <td>{formatDateTime(new Date(block.until * 1000).toISOString(), locale)}</td>
            <td>
              {canWrite ? (
                <button type="button" className="button-danger" onClick={() => void unblock(block)}>{t("unblock")}</button>
              ) : null}
            </td>
          </tr>
        ))}
      </DataTable>

      <Modal open={createOpen} title={t("modalTitle")} onClose={() => setCreateOpen(false)}>
        <ModalSaveForm className="section-stack" onSubmit={(event) => { event.preventDefault(); return create(); }}>
          <label className="field-stack">
            <span className="field-label">{t("ipLabel")}</span>
            <input value={ip} onChange={(event) => setIp(event.target.value)} maxLength={64} autoComplete="off" spellCheck={false} />
            <span className="field-help">{t("ipHelp")}</span>
          </label>
          <div className="two-col">
            <label className="field-stack">
              <span className="field-label">{t("scopeLabel")}</span>
              <Select value={scope} onChange={(event) => setScope(event.target.value === "net" ? "net" : "source")}>
                <option value="source">{t("scopes.source")}</option>
                <option value="net">{t("scopes.net")}</option>
              </Select>
            </label>
            <label className="field-stack">
              <span className="field-label">{t("minutesLabel")}</span>
              <input type="number" min={1} max={MAX_MINUTES} inputMode="numeric" value={minutes} onChange={(event) => setMinutes(event.target.value)} />
              <span className="field-help">{t("minutesHelp", { max: MAX_MINUTES })}</span>
            </label>
          </div>
          <label className="field-stack">
            <span className="field-label">{t("reasonLabel")}</span>
            <input value={reason} onChange={(event) => setReason(event.target.value)} maxLength={200} />
          </label>
          <div className="modal-actions">
            <button type="button" className="button-ghost" onClick={() => setCreateOpen(false)}>{t("cancel")}</button>
            <button type="submit" className="button-primary" disabled={!formValid || busy}>{t("save")}</button>
          </div>
        </ModalSaveForm>
      </Modal>
    </section>
  );
}
