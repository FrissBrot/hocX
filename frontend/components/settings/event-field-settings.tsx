"use client";

// Mandant-Einstellungen: eigene Namen (Alias) und Ausblenden für die Spezialfelder der Termine.
// Gilt überall, wo Termine angezeigt oder bearbeitet werden (useEventFieldConfig).
import { FormEvent, useEffect, useState } from "react";
import { useTranslations } from "next-intl";

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
    <section className="card">
      <div className="eyebrow">{t("eyebrow")}</div>
      <form className="grid" onSubmit={save}>
        <p className="muted">{t("description")}</p>
        <div className="event-field-settings">
          <span className="field-label">{t("columnField")}</span>
          <span className="field-label">{t("columnAlias")}</span>
          <span className="field-label">{t("columnHidden")}</span>
          {EVENT_SPECIAL_FIELDS.map((field) => (
            <div key={field} className="event-field-settings-row">
              <span>{t(`defaults.${field}`)}</span>
              <input
                value={draft[field].label}
                maxLength={60}
                placeholder={t(`defaults.${field}`)}
                aria-label={t("aliasFor", { field: t(`defaults.${field}`) })}
                onChange={(event) => setDraft({ ...draft, [field]: { ...draft[field], label: event.target.value } })}
              />
              <label className="studio-inline-check">
                <input
                  type="checkbox"
                  checked={draft[field].hidden}
                  onChange={(event) => setDraft({ ...draft, [field]: { ...draft[field], hidden: event.target.checked } })}
                />
                <span>{t("hide")}</span>
              </label>
            </div>
          ))}
        </div>
        <span className="field-help">{t("help")}</span>
        <div className="table-actions table-actions-start">
          <button type="submit" className="button-primary" disabled={saving}>
            {tCommon("save")}
          </button>
        </div>
      </form>
    </section>
  );
}
