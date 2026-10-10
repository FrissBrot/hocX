"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";

import { MfaProfilePanel } from "@/components/security/mfa-profile-panel";
import { Modal } from "@/components/ui/modal";
import { Tabs } from "@/components/ui/tabs";
import { locales, localeConfig } from "@/i18n/locale-config.generated";

type Props = {
  open: boolean;
  onClose: () => void;
  language: string;
  onLanguageChange: (lang: string) => void;
  protocolAccordionEnabled: boolean;
  onProtocolAccordionChange: (enabled: boolean) => void;
  onSave: () => void | Promise<void>;
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
  const t = useTranslations("settings.profileModal");
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
      onEscape={onSave}
      title={t("title")}
      description={t("description")}
      size="wide"
    >
      <Tabs
        activeId={activeTab}
        onChange={setActiveTab}
        tabs={[
          {
            id: "profil",
            label: t("tabs.profile"),
            content: (
              <div className="grid">
                <label className="field-stack">
                  <span className="field-label">{t("languageLabel")}</span>
                  <span className="profile-select">
                    <select value={language} onChange={(event) => onLanguageChange(event.target.value)}>
                      {locales.map((code) => (
                        <option key={code} value={code}>
                          {localeConfig[code].nativeLabel}
                        </option>
                      ))}
                    </select>
                  </span>
                </label>
                <label className="profile-toggle">
                  <span className="profile-toggle-text">
                    <span>{t("accordionLabel")}</span>
                    <span className="field-help">{t("accordionHint")}</span>
                  </span>
                  <input
                    type="checkbox"
                    role="switch"
                    checked={protocolAccordionEnabled}
                    onChange={(event) => onProtocolAccordionChange(event.target.checked)}
                  />
                  <span className="album-picker-switch-track" aria-hidden="true" />
                </label>
                <div className="table-actions table-actions-start">
                  <button type="button" className="button-secondary" onClick={onSave}>
                    {t("save")}
                  </button>
                  <button type="button" className="button-secondary button-danger" onClick={onLogout}>
                    {t("logout")}
                  </button>
                </div>
              </div>
            ),
          },
          {
            id: "sicherheit",
            label: t("tabs.security"),
            content: <MfaProfilePanel open={open && activeTab === "sicherheit"} />,
          },
        ]}
      />
    </Modal>
  );
}
