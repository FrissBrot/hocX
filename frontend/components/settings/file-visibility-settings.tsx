"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";

import { Select } from "@/components/ui/select";
import { useToast } from "@/contexts/toast-context";
import { browserApiFetch } from "@/lib/api/client";
import { ContextVisibilityModule } from "@/types/api";

// Organisation › Datenschutz › Sichtbarkeit von Dateien (Kontext-Freigaben, Migration 0196):
// Modul-Standards; Abgabe-Aufträge können sie im Auftragsformular überschreiben. Nur lesend und nur
// zusätzlich zu den Rollenrechten - durchgesetzt im Backend (context_visibility_service).
export function FileVisibilitySettings({ initialModules }: { initialModules: ContextVisibilityModule[] }) {
  const t = useTranslations("tenantSettings.privacy");
  const toast = useToast();
  const [modules, setModules] = useState(initialModules);
  const [busy, setBusy] = useState(false);

  async function save(module: ContextVisibilityModule, changes: Partial<Pick<ContextVisibilityModule, "audience" | "file_filter">>) {
    setBusy(true);
    try {
      const next = await browserApiFetch<ContextVisibilityModule[]>(`/api/context-visibility/${module.module}`, {
        method: "PUT",
        body: JSON.stringify({ audience: changes.audience ?? module.audience, file_filter: changes.file_filter ?? module.file_filter }),
      });
      setModules(next);
      toast(t("saved"), "success");
    } catch (error) {
      toast(error instanceof Error ? error.message : t("saveFailed"), "error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="card docverify-card settings-anchor" id="file-visibility">
      <div className="docverify-card-head">
        <h2 className="docverify-heading">{t("fileVisibility.title")}</h2>
      </div>
      <p className="muted">{t("fileVisibility.intro")}</p>
      {modules.map((module) => (
        <div key={module.module} className="file-visibility-module">
          <h3 className="docverify-heading">{t(`fileVisibility.module.${module.module}`)}</h3>
          <p className="field-help">{t(`fileVisibility.moduleHint.${module.module}`)}</p>
          <div className="grid two-col">
            <label className="field-stack">
              <span className="field-label">{t("fileVisibility.audienceLabel")}</span>
              <Select
                value={module.audience}
                disabled={busy || module.fixed}
                onChange={(event) => void save(module, { audience: event.target.value as ContextVisibilityModule["audience"] })}
              >
                {module.audiences.map((audience) => (
                  <option key={audience} value={audience}>{t(`fileVisibility.audience.${audience}`)}</option>
                ))}
              </Select>
            </label>
            {module.fixed ? null : (
              <label className="field-stack">
                <span className="field-label">{t("fileVisibility.filterLabel")}</span>
                <Select
                  value={module.file_filter}
                  disabled={busy}
                  onChange={(event) => void save(module, { file_filter: event.target.value as ContextVisibilityModule["file_filter"] })}
                >
                  <option value="images">{t("fileVisibility.filter.images")}</option>
                  <option value="all">{t("fileVisibility.filter.all")}</option>
                </Select>
              </label>
            )}
          </div>
        </div>
      ))}
    </section>
  );
}
