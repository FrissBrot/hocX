"use client";

import { Modal } from "@/components/ui/modal";
import { SessionInfo, TenantMembership } from "@/types/api";

type Props = {
  open: boolean;
  onClose: () => void;
  session: SessionInfo | null;
  onSelect: (membership: TenantMembership) => void;
  onOpenSettings: (membership: TenantMembership) => void;
  onSetDefault: (tenantId: number | null) => void;
};

export function TenantSelectorModal({ open, onClose, session, onSelect, onOpenSettings, onSetDefault }: Props) {
  const hasMultipleTenants = (session?.available_tenants.length ?? 0) > 1;

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Mandant wechseln"
      description="Wähle den Arbeitsbereich, in dem du gerade arbeiten möchtest. Als Admin kannst du hier auch die Mandant-Einstellungen öffnen."
      size="wide"
    >
      <div className="selection-list selection-grid tenant-tile-grid">
        {session?.available_tenants.map((membership) => {
          const isActive = membership.tenant_id === session.current_tenant?.id;
          const isDefault = membership.tenant_id === session.user?.default_tenant_id;
          return (
            <article key={membership.tenant_id} className={`selection-card tenant-tile${isActive ? " tenant-tile-active" : ""}`}>
              <div className="tenant-tile-image">
                {membership.tenant_profile_image_url ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img src={membership.tenant_profile_image_url} alt={membership.tenant_name} />
                ) : (
                  <span>{membership.tenant_name.slice(0, 1) || "T"}</span>
                )}
              </div>
              <div className="tenant-tile-body">
                <div className="tenant-tile-header">
                  <div>
                    <strong>{membership.tenant_name}</strong>
                    <div className="muted">{membership.role_code}</div>
                  </div>
                  {membership.role_code === "admin" ? (
                    <button
                      type="button"
                      className="button-ghost"
                      aria-label={`Einstellungen für ${membership.tenant_name}`}
                      onClick={() => onOpenSettings(membership)}
                    >
                      ⚙
                    </button>
                  ) : null}
                </div>

                <button type="button" className="button-inline tenant-tile-switch" onClick={() => onSelect(membership)} disabled={isActive}>
                  {isActive ? "Aktiv" : "Wechseln"}
                </button>

                {hasMultipleTenants ? (
                  <div className="tenant-tile-footer">
                    <label className="checkbox-line">
                      <input
                        type="checkbox"
                        checked={isDefault}
                        onChange={() => onSetDefault(isDefault ? null : membership.tenant_id)}
                      />
                      Als Standard-Mandant
                    </label>
                  </div>
                ) : null}
              </div>
            </article>
          );
        })}
      </div>
    </Modal>
  );
}
