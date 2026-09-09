"use client";

import { useEffect, useState } from "react";

import { MfaProfilePanel } from "@/components/security/mfa-profile-panel";
import { Modal } from "@/components/ui/modal";
import { Tabs } from "@/components/ui/tabs";

type Props = {
  open: boolean;
  onClose: () => void;
  language: string;
  onLanguageChange: (lang: string) => void;
  protocolAccordionEnabled: boolean;
  onProtocolAccordionChange: (enabled: boolean) => void;
  onSave: () => void;
  onLogout: () => void;
};

export function ProfileModal({
  open,
  onClose,
  language,
  onLanguageChange,
  protocolAccordionEnabled,
  onProtocolAccordionChange,
  onSave,
  onLogout,
}: Props) {
  const [activeTab, setActiveTab] = useState("profil");

  useEffect(() => {
    if (open) {
      setActiveTab("profil");
    }
  }, [open]);

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Benutzerprofil"
      description="Persönliche Einstellungen, Sprache und Sicherheit deines Kontos."
      size="wide"
    >
      <Tabs
        activeId={activeTab}
        onChange={setActiveTab}
        tabs={[
          {
            id: "profil",
            label: "Profil",
            content: (
              <div className="grid">
                <label className="field-stack">
                  <span className="field-label">Sprache</span>
                  <select value={language} onChange={(event) => onLanguageChange(event.target.value)}>
                    <option value="de">Deutsch</option>
                    <option value="en">English</option>
                    <option value="fr">Français</option>
                    <option value="it">Italiano</option>
                  </select>
                </label>
                <label className="field-radio-option">
                  <input
                    type="checkbox"
                    checked={protocolAccordionEnabled}
                    onChange={(event) => onProtocolAccordionChange(event.target.checked)}
                  />
                  <span className="field-radio-option-label">
                    <strong>Protokollpunkte automatisch einklappen</strong>
                    <small className="muted">Nur den aktiven Punkt geöffnet anzeigen.</small>
                  </span>
                </label>
                <div className="table-actions table-actions-start">
                  <button type="button" className="button-inline" onClick={onSave}>
                    Profil speichern
                  </button>
                  <button type="button" className="button-inline button-danger" onClick={onLogout}>
                    Logout
                  </button>
                </div>
              </div>
            ),
          },
          {
            id: "sicherheit",
            label: "Sicherheit",
            content: <MfaProfilePanel open={open && activeTab === "sicherheit"} />,
          },
        ]}
      />
    </Modal>
  );
}
