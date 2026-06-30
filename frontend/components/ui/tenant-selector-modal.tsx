"use client";

import { Modal } from "@/components/ui/modal";
import { SessionInfo, TenantMembership } from "@/types/api";

type Props = {
  open: boolean;
  onClose: () => void;
  session: SessionInfo | null;
  onSelect: (membership: TenantMembership) => void;
};

export function TenantSelectorModal({ open, onClose, session, onSelect }: Props) {
  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Mandant wechseln"
      description="Wähle den Arbeitsbereich, in dem du gerade arbeiten möchtest."
    >
      <div className="selection-list">
        {session?.available_tenants.map((membership) => (
          <button key={membership.tenant_id} type="button" className="selection-item" onClick={() => onSelect(membership)}>
            <div>
              <strong>{membership.tenant_name}</strong>
              <div className="muted">{membership.role_code}</div>
            </div>
            <span className="pill">{membership.tenant_id === session.current_tenant?.id ? "Aktiv" : "Wechseln"}</span>
          </button>
        ))}
      </div>
    </Modal>
  );
}
