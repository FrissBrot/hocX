"use client";

import { useCallback, useEffect, useState } from "react";
import { useLocale, useTranslations } from "next-intl";

import { ActionMenu } from "@/components/ui/action-menu";
import { Badge, type BadgeVariant } from "@/components/ui/badge";
import { DataTable, DataToolbar } from "@/components/ui/data-table";
import { FilterTabs } from "@/components/ui/filter-tabs";
import { Modal } from "@/components/ui/modal";
import { StatusBanner } from "@/components/ui/status-banner";
import { useToast } from "@/contexts/toast-context";
import { browserApiFetch } from "@/lib/api/client";
import { formatDateTime } from "@/lib/utils/format";

export type AdminVerificationRequest = {
  id: string;
  tenant_id: string;
  current_tenant_name: string;
  tenant_name: string;
  status: "pending" | "approved" | "rejected" | "withdrawn";
  message: string | null;
  requested_by_email: string | null;
  requested_at: string;
  decided_at: string | null;
  decided_by_email: string | null;
  decision_note: string | null;
};

export type AdminTenantVerification = {
  tenant_id: string;
  tenant_name: string;
  verified_at: string | null;
  verified_by_email: string | null;
  note: string | null;
  revoked_at: string | null;
  revoked_reason: string | null;
  show_identity: boolean;
  requests: AdminVerificationRequest[];
};

type StatusFilter = "pending" | "approved" | "rejected" | "withdrawn" | "all";
type Decision = { kind: "approve" | "reject" | "revoke"; tenantId: string; tenantName: string };

const STATUS_VARIANTS: Record<AdminVerificationRequest["status"], BadgeVariant> = {
  pending: "info",
  approved: "success",
  rejected: "danger",
  withdrawn: "neutral",
};

type TFunc = ReturnType<typeof useTranslations>;

// Notiz eines durch Umbenennung zurückgezogenen Antrags ist ein Code, kein Text
function noteText(t: TFunc, note: string | null): string | null {
  return note === "name_changed" ? t("tenant.withdrawnByRename") : note;
}

// Backend-Fehler kommen als Schlüssel (z. B. "apiError.verificationNoPending")
function errorMessage(t: TFunc, error: unknown): string {
  const raw = error instanceof Error ? error.message : "";
  const key = raw.startsWith("apiError.") ? `errors.${raw.slice("apiError.".length)}` : null;
  return key && t.has(key) ? t(key) : t("errors.generic");
}

function DecisionModal({ decision, onClose, onDone }: { decision: Decision | null; onClose: () => void; onDone: (state: AdminTenantVerification) => void }) {
  const t = useTranslations("admin.verification");
  const toast = useToast();
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => setNote(""), [decision]);

  if (!decision) return null;
  const noteRequired = decision.kind === "reject";

  async function submit() {
    if (!decision) return;
    setBusy(true);
    try {
      const state = await browserApiFetch<AdminTenantVerification>(`/api/admin/tenants/${decision.tenantId}/identity-verification/${decision.kind}`, {
        method: "POST",
        body: JSON.stringify({ note: note.trim() || null }),
      });
      toast(t(`done.${decision.kind}`, { name: decision.tenantName }), "success");
      onDone(state);
      onClose();
    } catch (error) {
      toast(errorMessage(t, error), "error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal open title={t(`modal.${decision.kind}Title`, { name: decision.tenantName })} onClose={onClose}>
      <div className="grid">
        <p className="muted">{t(`modal.${decision.kind}Hint`)}</p>
        <label className="field-stack">
          <span className="field-label">{noteRequired ? t("modal.reasonRequired") : t("modal.note")}</span>
          <textarea rows={3} maxLength={2000} value={note} placeholder={t(`modal.${decision.kind}Placeholder`)} onChange={(event) => setNote(event.target.value)} />
        </label>
        <div className="modal-actions">
          <button type="button" className="button-secondary" onClick={onClose}>{t("modal.cancel")}</button>
          <button
            type="button"
            className={decision.kind === "approve" ? "button-primary" : "button-danger"}
            disabled={busy || (noteRequired && !note.trim())}
            onClick={() => void submit()}
          >
            {t(`actions.${decision.kind}`)}
          </button>
        </div>
      </div>
    </Modal>
  );
}

// Seite /admin/verifications: Anträge auf Verifizierung der Organisation
export function AdminVerificationRequests({ initialRequests }: { initialRequests: AdminVerificationRequest[] }) {
  const t = useTranslations("admin.verification");
  const locale = useLocale();
  const toast = useToast();
  const [filter, setFilter] = useState<StatusFilter>("pending");
  const [requests, setRequests] = useState(initialRequests);
  const [decision, setDecision] = useState<Decision | null>(null);

  const load = useCallback(
    async (status: StatusFilter) => {
      try {
        setRequests(await browserApiFetch<AdminVerificationRequest[]>(`/api/admin/identity-verification-requests?status=${status}`));
      } catch (error) {
        toast(errorMessage(t, error), "error");
      }
    },
    [t, toast]
  );

  function changeFilter(next: StatusFilter) {
    setFilter(next);
    void load(next);
  }

  return (
    <div className="grid">
      <DataToolbar title={t("title")} description={t("description")} />
      <FilterTabs
        options={(["pending", "approved", "rejected", "withdrawn", "all"] as const).map((value) => ({ value, label: t(`filter.${value}`) }))}
        value={filter}
        onChange={changeFilter}
      />
      <DataTable columns={[t("columns.organisation"), t("columns.message"), t("columns.requested"), t("columns.status"), t("columns.actions")]} emptyMessage={t("empty")}>
        {requests.map((row) => (
          <tr key={row.id}>
            <td>
              <strong>{row.current_tenant_name}</strong>
              {row.tenant_name !== row.current_tenant_name && <div className="muted">{t("requestedAs", { name: row.tenant_name })}</div>}
            </td>
            <td className="admin-verification-message">{row.message || "—"}</td>
            <td className="muted">
              {formatDateTime(row.requested_at, locale)}
              {row.requested_by_email && <div>{row.requested_by_email}</div>}
            </td>
            <td>
              <Badge variant={STATUS_VARIANTS[row.status]}>{t(`status.${row.status}`)}</Badge>
              {row.decision_note && <div className="muted">{noteText(t, row.decision_note)}</div>}
            </td>
            <td>
              {row.status === "pending" && (
                <ActionMenu
                  items={[
                    { label: t("actions.approve"), onClick: () => setDecision({ kind: "approve", tenantId: row.tenant_id, tenantName: row.current_tenant_name }) },
                    { label: t("actions.reject"), onClick: () => setDecision({ kind: "reject", tenantId: row.tenant_id, tenantName: row.current_tenant_name }), danger: true },
                  ]}
                />
              )}
            </td>
          </tr>
        ))}
      </DataTable>
      <DecisionModal decision={decision} onClose={() => setDecision(null)} onDone={() => void load(filter)} />
    </div>
  );
}

// Tab «Verifizierung» im Mandanten-Dialog
export function AdminTenantVerificationPanel({ tenantId, tenantName }: { tenantId: string; tenantName: string }) {
  const t = useTranslations("admin.verification");
  const locale = useLocale();
  const toast = useToast();
  const [state, setState] = useState<AdminTenantVerification | null>(null);
  const [decision, setDecision] = useState<Decision | null>(null);

  useEffect(() => {
    let cancelled = false;
    browserApiFetch<AdminTenantVerification>(`/api/admin/tenants/${tenantId}/identity-verification`)
      .then((value) => { if (!cancelled) setState(value); })
      .catch((error: unknown) => toast(errorMessage(t, error), "error"));
    return () => { cancelled = true; };
  }, [tenantId, t, toast]);

  if (!state) {
    return <p className="muted">{t("loading")}</p>;
  }
  const pending = state.requests.find((row) => row.status === "pending");
  const open = (kind: Decision["kind"]) => setDecision({ kind, tenantId, tenantName });

  return (
    <div className="grid">
      <section className="admin-form-section">
        <div className="admin-section-title">{t("tenant.title")}</div>
        <div className="admin-verification-status">
          {state.verified_at ? (
            <Badge variant="success" dot>{t("tenant.verified", { date: formatDateTime(state.verified_at, locale) })}</Badge>
          ) : pending ? (
            <Badge variant="info" dot>{t("status.pending")}</Badge>
          ) : (
            <Badge variant="neutral">{t("tenant.notVerified")}</Badge>
          )}
          {state.verified_by_email && <span className="muted">{t("tenant.by", { email: state.verified_by_email })}</span>}
        </div>
        {state.note && <p className="muted">{t("tenant.note", { note: state.note })}</p>}
        {state.revoked_reason && !state.verified_at && (
          <StatusBanner tone="neutral" message={t(`tenant.revoked.${state.revoked_reason === "name_changed" ? "name_changed" : "admin"}`, { date: formatDateTime(state.revoked_at, locale) })} />
        )}
        {state.verified_at && !state.show_identity && <StatusBanner tone="neutral" message={t("tenant.hidden")} />}
        <div className="docexport-actions-row">
          {pending && <button type="button" className="button-danger" onClick={() => open("reject")}>{t("actions.reject")}</button>}
          {state.verified_at ? (
            <button type="button" className="button-danger" onClick={() => open("revoke")}>{t("actions.revoke")}</button>
          ) : (
            <button type="button" className="button-primary" onClick={() => open("approve")}>{t("actions.approve")}</button>
          )}
        </div>
      </section>
      <section className="admin-form-section">
        <div className="admin-section-title">{t("tenant.history")}</div>
        <DataTable columns={[t("columns.requested"), t("columns.message"), t("columns.status")]} emptyMessage={t("tenant.noRequests")}>
          {state.requests.map((row) => (
            <tr key={row.id}>
              <td className="muted">
                {formatDateTime(row.requested_at, locale)}
                {row.tenant_name !== state.tenant_name && <div>{t("requestedAs", { name: row.tenant_name })}</div>}
              </td>
              <td className="admin-verification-message">{row.message || "—"}</td>
              <td>
                <Badge variant={STATUS_VARIANTS[row.status]}>{t(`status.${row.status}`)}</Badge>
                {row.decision_note && <div className="muted">{noteText(t, row.decision_note)}</div>}
              </td>
            </tr>
          ))}
        </DataTable>
      </section>
      <DecisionModal decision={decision} onClose={() => setDecision(null)} onDone={setState} />
    </div>
  );
}
