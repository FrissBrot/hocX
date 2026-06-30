"use client";

import { Modal } from "@/components/ui/modal";

type Props = {
  open: boolean;
  onClose: () => void;
  language: string;
  onLanguageChange: (lang: string) => void;
  onSave: () => void;
  onLogout: () => void;
};

export function ProfileModal({ open, onClose, language, onLanguageChange, onSave, onLogout }: Props) {
  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Benutzerprofil"
      description="Passe deine Sprache an oder melde dich ab."
    >
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
        <div className="table-actions table-actions-start">
          <button type="button" className="button-inline" onClick={onSave}>
            Profil speichern
          </button>
          <button type="button" className="button-inline button-danger" onClick={onLogout}>
            Logout
          </button>
        </div>
      </div>
    </Modal>
  );
}
