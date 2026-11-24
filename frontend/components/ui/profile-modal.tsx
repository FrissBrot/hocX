"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";

import { MfaProfilePanel } from "@/components/security/mfa-profile-panel";
import { PasswordChangePanel } from "@/components/security/password-change-panel";
import { SessionsPanel } from "@/components/security/sessions-panel";
import { DocsLink } from "@/components/ui/help-popover";
import { NotificationPreferencesPanel } from "@/components/notifications/notification-preferences-panel";
import { Modal } from "@/components/ui/modal";
import { ProtectedExportForm } from "@/components/ui/protected-export-modal";
import { Tabs } from "@/components/ui/tabs";
import { locales, localeConfig } from "@/i18n/locale-config.generated";
import { Select } from "@/components/ui/select";

type Props = {
  open: boolean;
  onClose: () => void;
  language: string;
  onLanguageChange: (lang: string) => void;
  onSave: () => void | Promise<void>;
  onLogout: () => void;
  /** Reiter beim Öffnen (Direktlink ?profile=notifications aus E-Mails), sonst «profil» */
  initialTab?: string;
};

export function ProfileModal({
  open,
  onClose,
  language,
  onLanguageChange,
  onSave,
  onLogout,
  initialTab,
}: Props) {
  const t = useTranslations("settings.profileModal");
  const [activeTab, setActiveTab] = useState(initialTab ?? "profil");

  useEffect(() => {
    if (open) {
      setActiveTab(initialTab ?? "profil");
    }
  }, [open, initialTab]);

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
                    <Select value={language} onChange={(event) => onLanguageChange(event.target.value)}>
                      {locales.map((code) => (
                        <option key={code} value={code}>
                          {localeConfig[code].nativeLabel}
                        </option>
                      ))}
                    </Select>
                  </span>
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
            id: "benachrichtigungen",
            label: t("tabs.notifications"),
            content: (
              <div className="grid">
                <NotificationPreferencesPanel open={open && activeTab === "benachrichtigungen"} />
                <DocsLink page="benachrichtigungen">{t("docs.notifications")}</DocsLink>
              </div>
            ),
          },
          {
            id: "sicherheit",
            label: t("tabs.security"),
            content: (
              <div className="grid">
                <PasswordChangePanel />
                <MfaProfilePanel open={open && activeTab === "sicherheit"} />
                <SessionsPanel open={open && activeTab === "sicherheit"} />
                <DocsLink page="konto" anchor="mfa">{t("docs.security")}</DocsLink>
              </div>
            ),
          },
          {
            id: "daten",
            label: t("tabs.data"),
            content: (
              <div className="grid">
                <p className="muted">{t("personalData.description")}</p>
                <ProtectedExportForm path="/api/users/me/personal-data" fallbackFilename="hocx-data.zip" submitLabel={t("personalData.download")} />
              </div>
            ),
          },
        ]}
      />
    </Modal>
  );
}
