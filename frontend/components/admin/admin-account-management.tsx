"use client";

import { FormEvent, useState } from "react";
import { useTranslations } from "next-intl";

import { DataTable, DataToolbar } from "@/components/ui/data-table";
import { Modal, ModalSaveForm } from "@/components/ui/modal";
import { browserApiFetch } from "@/lib/api/client";
import { useToast } from "@/contexts/toast-context";
import { useConfirm } from "@/contexts/confirm-context";
import { PlatformAdminSummary } from "@/types/api";

type Props = {
  initialAdmins: PlatformAdminSummary[];
  currentAdminId: string;
};

export function AdminAccountManagement({ initialAdmins, currentAdminId }: Props) {
  const t = useTranslations("admin.accountManagement");
  const showToast = useToast();
  const confirm = useConfirm();
  const [admins, setAdmins] = useState(initialAdmins);
  const [modalOpen, setModalOpen] = useState(false);
  const [email, setEmail] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<"owner" | "support">("owner");

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    try {
      const created = await browserApiFetch<PlatformAdminSummary>("/api/admin/admins", {
        method: "POST",
        body: JSON.stringify({ email, display_name: displayName, password, role }),
      });
      setAdmins((current) => [...current, created].sort((a, b) => a.email.localeCompare(b.email)));
      setModalOpen(false);
      setEmail("");
      setDisplayName("");
      setPassword("");
      setRole("owner");
      showToast(t("toasts.created"), "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("toasts.createFailed"), "error");
    }
  }

  async function toggleRole(admin: PlatformAdminSummary) {
    const nextRole = admin.role === "owner" ? "support" : "owner";
    // Downgrading the OWN account had neither a confirmation nor a self-protection guard
    // (unlike the Deaktivieren button right next to it) - a misclick here instantly loses
    // write access to this whole panel, recoverable only by asking another owner to
    // restore it (audit A3, 2026-08-16).
    if (admin.id === currentAdminId && nextRole === "support") {
      const ok = await confirm({
        message: t("toasts.selfDowngradeConfirm"),
        tone: "danger",
        confirmLabel: t("setReadOnly"),
      });
      if (!ok) return;
    }
    try {
      const updated = await browserApiFetch<PlatformAdminSummary>(`/api/admin/admins/${admin.id}`, {
        method: "PATCH",
        body: JSON.stringify({ role: nextRole }),
      });
      setAdmins((current) => current.map((item) => (item.id === updated.id ? updated : item)));
      showToast(t("toasts.updated"), "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("toasts.updateFailed"), "error");
    }
  }

  async function toggleActive(admin: PlatformAdminSummary) {
    if (admin.is_active) {
      const ok = await confirm({
        message: t("toasts.deactivateConfirm", { name: admin.display_name }),
        tone: "danger",
        confirmLabel: t("deactivate"),
      });
      if (!ok) return;
    }
    try {
      const updated = await browserApiFetch<PlatformAdminSummary>(`/api/admin/admins/${admin.id}`, {
        method: "PATCH",
        body: JSON.stringify({ is_active: !admin.is_active }),
      });
      setAdmins((current) => current.map((item) => (item.id === updated.id ? updated : item)));
      showToast(t("toasts.updated"), "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("toasts.updateFailed"), "error");
    }
  }

  return (
    <div className="grid">
      <DataToolbar
        title={t("title")}
        description={t("description")}
        actions={
          <button type="button" className="button-secondary" onClick={() => setModalOpen(true)}>
            {t("newAdmin")}
          </button>
        }
      />

      <DataTable columns={[t("columns.name"), t("columns.email"), t("columns.role"), t("columns.status"), t("columns.actions")]} emptyMessage={t("emptyAdmins")}>
        {admins.map((admin) => (
          <tr key={admin.id}>
            <td>
              <strong>{admin.display_name}</strong>
              {admin.id === currentAdminId ? <div className="muted">{t("you")}</div> : null}
            </td>
            <td>{admin.email}</td>
            <td>{admin.role === "owner" ? t("fullAccess") : t("readOnlyAccess")}</td>
            <td>{admin.is_active ? t("active") : t("deactivated")}</td>
            <td>
              <div className="table-actions table-actions-start">
                <button type="button" className="button-secondary" onClick={() => void toggleRole(admin)}>
                  {admin.role === "owner" ? t("setReadOnly") : t("setFullAccess")}
                </button>
                <button
                  type="button"
                  className={`button-secondary${admin.is_active ? " button-danger" : ""}`}
                  onClick={() => void toggleActive(admin)}
                  disabled={admin.id === currentAdminId && admin.is_active}
                >
                  {admin.is_active ? t("deactivate") : t("activate")}
                </button>
              </div>
            </td>
          </tr>
        ))}
      </DataTable>

      <Modal open={modalOpen} onClose={() => setModalOpen(false)} title={t("newAdminModalTitle")} description={t("newAdminModalDescription")}>
        <ModalSaveForm className="grid" onSubmit={submit}>
          <label className="field-stack">
            <span className="field-label">{t("name")}</span>
            <input value={displayName} onChange={(event) => setDisplayName(event.target.value)} required />
          </label>
          <label className="field-stack">
            <span className="field-label">{t("email")}</span>
            <input value={email} onChange={(event) => setEmail(event.target.value)} required />
          </label>
          <label className="field-stack">
            <span className="field-label">{t("password")}</span>
            <input type="password" autoComplete="new-password" value={password} onChange={(event) => setPassword(event.target.value)} required minLength={8} />
          </label>
          <label className="field-stack">
            <span className="field-label">{t("columns.role")}</span>
            <select value={role} onChange={(event) => setRole(event.target.value as "owner" | "support")}>
              <option value="owner">{t("fullAccess")}</option>
              <option value="support">{t("readOnlyAccess")}</option>
            </select>
          </label>
          <div className="table-actions table-actions-start">
            <button data-modal-save type="submit" className="button-secondary">
              {t("create")}
            </button>
          </div>
        </ModalSaveForm>
      </Modal>
    </div>
  );
}
