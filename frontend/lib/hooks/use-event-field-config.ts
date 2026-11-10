"use client";

// Spezialfelder der Termine (Spezial 1–3, Spezial Text 1–3): eigener Name (Alias) und
// Ausblenden je Mandant, eingestellt unter Mandant-Einstellungen. Einmal pro Seite geladen und
// geteilt; nach dem Speichern in den Einstellungen sofort überall aktualisiert.
import { useCallback, useEffect, useState } from "react";

import { browserApiFetch } from "@/lib/api/client";

export const EVENT_SPECIAL_FIELDS = ["spezial1_ids", "spezial2_ids", "spezial3_ids", "spezial_text1", "spezial_text2", "spezial_text3"] as const;
export type EventSpecialField = (typeof EVENT_SPECIAL_FIELDS)[number];
export type EventFieldSetting = { label: string; hidden: boolean };
export type EventFieldConfig = Record<EventSpecialField, EventFieldSetting>;

export const DEFAULT_EVENT_FIELD_CONFIG: EventFieldConfig = Object.fromEntries(
  EVENT_SPECIAL_FIELDS.map((field) => [field, { label: "", hidden: false }])
) as EventFieldConfig;

let cached: EventFieldConfig | null = null;
let loading: Promise<EventFieldConfig> | null = null;
const listeners = new Set<(config: EventFieldConfig) => void>();

function load(): Promise<EventFieldConfig> {
  if (cached) return Promise.resolve(cached);
  loading ??= browserApiFetch<EventFieldConfig>("/api/event-field-config")
    .then((config) => {
      cached = { ...DEFAULT_EVENT_FIELD_CONFIG, ...(config ?? {}) };
      return cached;
    })
    .catch(() => {
      loading = null;
      return DEFAULT_EVENT_FIELD_CONFIG;
    });
  return loading;
}

/** Nach dem Speichern in den Einstellungen: alle offenen Ansichten übernehmen die neuen Namen. */
export function publishEventFieldConfig(config: EventFieldConfig) {
  cached = config;
  loading = Promise.resolve(config);
  for (const listener of listeners) listener(config);
}

export function isEventSpecialField(field: string): field is EventSpecialField {
  return (EVENT_SPECIAL_FIELDS as readonly string[]).includes(field);
}

export function useEventFieldConfig() {
  const [config, setConfig] = useState<EventFieldConfig>(cached ?? DEFAULT_EVENT_FIELD_CONFIG);

  useEffect(() => {
    let active = true;
    void load().then((loaded) => {
      if (active) setConfig(loaded);
    });
    listeners.add(setConfig);
    return () => {
      active = false;
      listeners.delete(setConfig);
    };
  }, []);

  /** Alias des Felds, sonst der übergebene Standardname. Andere Felder bleiben unverändert. */
  const label = useCallback(
    (field: string, fallback: string) => (isEventSpecialField(field) && config[field]?.label.trim() ? config[field].label.trim() : fallback),
    [config]
  );
  /** Ausgeblendete Spezialfelder erscheinen nirgends (Werte bleiben gespeichert). */
  const hidden = useCallback((field: string) => isEventSpecialField(field) && !!config[field]?.hidden, [config]);

  return { config, label, hidden };
}
