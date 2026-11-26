"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";

import { FileVisibilitySettings } from "@/components/settings/file-visibility-settings";
import { TenantDataExportPanel } from "@/components/settings/tenant-data-export";
import { useToast } from "@/contexts/toast-context";
import { browserApiFetch } from "@/lib/api/client";
import { ContextVisibilityModule } from "@/types/api";

export type PrivacySettingsState = {
  statistics_per_person_public: boolean;
  privacy_notice_url: string | null;
};

const API = "/api/privacy-settings";

/** Wie das Backend (privacy_settings._https_only): leer oder https:// mit Adresse, ohne Leerzeichen. */
export function isValidNoticeUrl(value: string): boolean {
  const trimmed = value.trim();
  if (trimmed === "") return true;
  if (/\s/.test(trimmed) || !trimmed.startsWith("https://")) return false;
  try {
    return new URL(trimmed).hostname !== "";
  } catch {
    return false;
  }
}

// Mandanten-Einstellungen → Datenschutz (nur Mandanten-Admins).
export function PrivacySettings({ initialState, fileVisibility }: { initialState: PrivacySettingsState; fileVisibility?: ContextVisibilityModule[] | null }) {
  const t = useTranslations("tenantSettings.privacy");
  const toast = useToast();
  const [state, setState] = useState(initialState);
  const [busy, setBusy] = useState(false);
  const [noticeUrl, setNoticeUrl] = useState(initialState.privacy_notice_url ?? "");
  const noticeUrlValid = isValidNoticeUrl(noticeUrl);

  async function save(changes: Partial<Record<keyof PrivacySettingsState, boolean | string>>) {
    setBusy(true);
    try {
      setState(await browserApiFetch<PrivacySettingsState>(API, { method: "PATCH", body: JSON.stringify(changes) }));
      toast(t("saved"), "success");
    } catch (error) {
      toast(error instanceof Error ? error.message : t("saveFailed"), "error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="docverify">
      <div className="grid docverify-main">
        <p className="muted docverify-intro">{t("intro")}</p>
        <section className="card docverify-card settings-anchor" id="privacy-statistics">
          <div className="docverify-card-head">
            <h2 className="docverify-heading">{t("statisticsTitle")}</h2>
          </div>
          <label className="docverify-toggle">
            <input
              type="checkbox"
              role="switch"
              disabled={busy}
              checked={state.statistics_per_person_public}
              onChange={(event) => void save({ statistics_per_person_public: event.target.checked })}
            />
            <span className="album-picker-switch-track" aria-hidden="true" />
            <span className="docverify-toggle-text">
              <span className="docverify-toggle-label">{t("statisticsPerPersonPublic")}</span>
              <span className="docverify-toggle-hint">{t("statisticsPerPersonPublicHint")}</span>
            </span>
          </label>
        </section>
        <section className="card docverify-card settings-anchor" id="privacy-notice">
          <div className="docverify-card-head">
            <h2 className="docverify-heading">{t("noticeTitle")}</h2>
          </div>
          <label className="field-stack">
            <span className="field-label">{t("noticeUrl")}</span>
            <input
              type="url"
              inputMode="url"
              placeholder="https://"
              value={noticeUrl}
              maxLength={500}
              aria-invalid={!noticeUrlValid || undefined}
              onChange={(event) => setNoticeUrl(event.target.value)}
            />
            {!noticeUrlValid ? <span className="field-help">{t("noticeUrlInvalid")}</span> : null}
            <span className="field-help">{t("noticeUrlHint")}</span>
          </label>
          <div className="table-actions table-actions-start">
            <button
              type="button"
              className="button-secondary"
              disabled={busy || noticeUrl.trim() === (state.privacy_notice_url ?? "") || !noticeUrlValid}
              onClick={() => void save({ privacy_notice_url: noticeUrl.trim() })}
            >
              {t("noticeSave")}
            </button>
          </div>
        </section>
        {fileVisibility ? <FileVisibilitySettings initialModules={fileVisibility} /> : null}
        <TenantDataExportPanel />
      </div>
    </div>
  );
}
