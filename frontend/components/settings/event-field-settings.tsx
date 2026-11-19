"use client";

// Mandant-Einstellungen: eigene Namen (Alias) und Ausblenden für die Spezialfelder der Termine.
// Gilt überall, wo Termine angezeigt oder bearbeitet werden (useEventFieldConfig).
import { FormEvent, useEffect, useState } from "react";
import { useTranslations } from "next-intl";

import { ProfileSection } from "@/components/settings/profile-section";
import { DataTable } from "@/components/ui/data-table";
import { useToast } from "@/contexts/toast-context";
import { browserApiFetch } from "@/lib/api/client";
import {
  EVENT_SPECIAL_FIELDS,
  EventFieldConfig,
  publishEventFieldConfig,
  useEventFieldConfig,
} from "@/lib/hooks/use-event-field-config";

export function EventFieldSettings() {
  const t = useTranslations("tenantSettings.eventFields");
  const tCommon = useTranslations("common");
  const showToast = useToast();
  const { config } = useEventFieldConfig();
  const [draft, setDraft] = useState<EventFieldConfig>(config);
  const [saving, setSaving] = useState(false);

  useEffect(() => setDraft(config), [config]);

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true);
    try {
      const saved = await browserApiFetch<EventFieldConfig>("/api/event-field-config", { method: "PUT", body: JSON.stringify(draft) });
      publishEventFieldConfig(saved);
      showToast(t("saved"), "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("saveFailed"), "error");
    } finally {
      setSaving(false);
    }
  }

  return (
    <ProfileSection id="event-fields" title={t("eyebrow")} description={t("description")}>
      <form className="grid" onSubmit={save}>
        <DataTable columns={[{ key: "field", label: t("columnField") }, { key: "alias", label: t("columnAlias") }, { key: "hidden", label: t("hide") }]} className="event-field-table">
          {EVENT_SPECIAL_FIELDS.map((field) => (
            <tr key={field} className={draft[field].hidden ? "event-field-row-hidden" : undefined}>
              <td className="event-field-name">{t(`defaults.${field}`)}</td>
              <td>
                <input
                  value={draft[field].label}
                  maxLength={60}
                  placeholder={t(`defaults.${field}`)}
                  aria-label={t("aliasFor", { field: t(`defaults.${field}`) })}
                  onChange={(event) => setDraft({ ...draft, [field]: { ...draft[field], label: event.target.value } })}
                />
              </td>
              <td>
                <label className="studio-inline-check">
                  <input
                    type="checkbox"
                    aria-label={t("hideFor", { field: t(`defaults.${field}`) })}
                    checked={draft[field].hidden}
                    onChange={(event) => setDraft({ ...draft, [field]: { ...draft[field], hidden: event.target.checked } })}
                  />
                </label>
              </td>
            </tr>
          ))}
        </DataTable>
        <span className="field-help">{t("help")}</span>
        <div className="table-actions table-actions-start">
          <button type="submit" className="button-primary" disabled={saving}>
            {tCommon("save")}
          </button>
        </div>
      </form>
    </ProfileSection>
  );
}
