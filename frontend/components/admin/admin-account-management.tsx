"use client";

import { FormEvent, useState } from "react";

import { DataTable, DataToolbar } from "@/components/ui/data-table";
import { Modal } from "@/components/ui/modal";
import { browserApiFetch } from "@/lib/api/client";
import { useToast } from "@/contexts/toast-context";
import { PlatformAdminSummary } from "@/types/api";

type Props = {
  initialAdmins: PlatformAdminSummary[];
  currentAdminId: number;
};

export function AdminAccountManagement({ initialAdmins, currentAdminId }: Props) {
  const showToast = useToast();
  const [admins, setAdmins] = useState(initialAdmins);
  const [modalOpen, setModalOpen] = useState(false);
  const [email, setEmail] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [password, setPassword] = useState("");

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    try {
      const created = await browserApiFetch<PlatformAdminSummary>("/api/admin/admins", {
        method: "POST",
        body: JSON.stringify({ email, display_name: displayName, password }),
      });
      setAdmins((current) => [...current, created].sort((a, b) => a.email.localeCompare(b.email)));
      setModalOpen(false);
      setEmail("");
      setDisplayName("");
      setPassword("");
      showToast("Admin-Account erstellt", "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : "Admin-Account konnte nicht erstellt werden", "error");
    }
  }

  async function toggleActive(admin: PlatformAdminSummary) {
    try {
      const updated = await browserApiFetch<PlatformAdminSummary>(`/api/admin/admins/${admin.id}`, {
        method: "PATCH",
        body: JSON.stringify({ is_active: !admin.is_active }),
      });
      setAdmins((current) => current.map((item) => (item.id === updated.id ? updated : item)));
      showToast("Admin-Account aktualisiert", "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : "Admin-Account konnte nicht aktualisiert werden", "error");
    }
  }

  return (
    <div className="grid">
      <DataToolbar
        title="Admin-Accounts"
        description="Zugang zum Platform-Admin-Panel selbst - getrennt von allen Mandanten-Benutzern."
        actions={
          <button type="button" className="button-inline" onClick={() => setModalOpen(true)}>
            Neuer Admin
          </button>
        }
      />

      <DataTable columns={["Name", "E-Mail", "Status", "Aktionen"]} emptyMessage="Keine Admin-Accounts gefunden.">
        {admins.map((admin) => (
          <tr key={admin.id}>
            <td>
              <strong>{admin.display_name}</strong>
              {admin.id === currentAdminId ? <div className="muted">Du</div> : null}
            </td>
            <td>{admin.email}</td>
            <td>{admin.is_active ? "Aktiv" : "Deaktiviert"}</td>
            <td>
              <div className="table-actions table-actions-start">
                <button
                  type="button"
                  className={`button-inline${admin.is_active ? " button-danger" : ""}`}
                  onClick={() => void toggleActive(admin)}
                  disabled={admin.id === currentAdminId && admin.is_active}
                >
                  {admin.is_active ? "Deaktivieren" : "Aktivieren"}
                </button>
              </div>
            </td>
          </tr>
        ))}
      </DataTable>

      <Modal open={modalOpen} onClose={() => setModalOpen(false)} title="Neuer Admin-Account" description="Legt einen weiteren Zugang zum Platform-Admin-Panel an.">
        <form className="grid" onSubmit={submit}>
          <label className="field-stack">
            <span className="field-label">Name</span>
            <input value={displayName} onChange={(event) => setDisplayName(event.target.value)} required />
          </label>
          <label className="field-stack">
            <span className="field-label">E-Mail</span>
            <input value={email} onChange={(event) => setEmail(event.target.value)} required />
          </label>
          <label className="field-stack">
            <span className="field-label">Passwort</span>
            <input type="password" value={password} onChange={(event) => setPassword(event.target.value)} required minLength={8} />
          </label>
          <div className="table-actions table-actions-start">
            <button type="submit" className="button-inline">
              Erstellen
            </button>
          </div>
        </form>
      </Modal>
    </div>
  );
}
