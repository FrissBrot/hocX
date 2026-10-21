"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";

import { TenantDataExportPanel } from "@/components/settings/tenant-data-export";
import { useToast } from "@/contexts/toast-context";
import { browserApiFetch } from "@/lib/api/client";

export type PrivacySettingsState = {
  statistics_per_person_public: boolean;
};

const API = "/api/privacy-settings";

// Mandanten-Einstellungen → Datenschutz (nur Mandanten-Admins).
export function PrivacySettings({ initialState }: { initialState: PrivacySettingsState }) {
  const t = useTranslations("tenantSettings.privacy");
  const toast = useToast();
  const [state, setState] = useState(initialState);
  const [busy, setBusy] = useState(false);

  async function toggle(key: keyof PrivacySettingsState, value: boolean) {
    setBusy(true);
    try {
      setState(await browserApiFetch<PrivacySettingsState>(API, { method: "PATCH", body: JSON.stringify({ [key]: value }) }));
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
        <section className="card docverify-card">
          <div className="docverify-card-head">
            <h2 className="docverify-heading">{t("statisticsTitle")}</h2>
          </div>
          <label className="docverify-toggle">
            <input
              type="checkbox"
              role="switch"
              disabled={busy}
              checked={state.statistics_per_person_public}
              onChange={(event) => void toggle("statistics_per_person_public", event.target.checked)}
            />
            <span className="album-picker-switch-track" aria-hidden="true" />
            <span className="docverify-toggle-text">
              <span className="docverify-toggle-label">{t("statisticsPerPersonPublic")}</span>
              <span className="docverify-toggle-hint">{t("statisticsPerPersonPublicHint")}</span>
            </span>
          </label>
        </section>
        <TenantDataExportPanel />
      </div>
    </div>
  );
}
