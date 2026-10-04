"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { SearchableSelect } from "@/components/ui/searchable-select";
import { browserApiFetch } from "@/lib/api/client";
import { CYCLE_OFFSET_OPTIONS, cycleOffsetLabel } from "@/components/submission-assignments/submission-assignment-form";
import type { CycleConfigSummary } from "@/types/api";

type CycleSelection = { cycle_config_id?: string | null; cycle_offset?: number };

export function ChartCycleSelection({ config, onChange }: { config: CycleSelection; onChange: (config: CycleSelection) => void }) {
  const t = useTranslations("submissionAssignments");
  const tChart = useTranslations("protocols.chart");
  const [configs, setConfigs] = useState<CycleConfigSummary[]>([]);
  useEffect(() => {
    let cancelled = false;
    browserApiFetch<CycleConfigSummary[]>("/api/cycle-configs")
      .then((rows) => { if (!cancelled) setConfigs(rows ?? []); })
      .catch(() => { if (!cancelled) setConfigs([]); });
    return () => { cancelled = true; };
  }, []);
  return (
    <div className="field-stack">
      <span className="field-label">{t("cycleLabel")}</span>
      <SearchableSelect
        options={configs}
        getId={(c) => c.id}
        getLabel={(c) => c.name}
        value={config.cycle_config_id || null}
        nullLabel={t("allCyclesNoFilter")}
        onChange={(c) => onChange({ cycle_config_id: c?.id ?? null, cycle_offset: config.cycle_offset ?? 0 })}
      />
      {config.cycle_config_id && (
        <div className="subm-edit-chips">
          {CYCLE_OFFSET_OPTIONS.map((offset) => (
            <button key={offset} type="button" className="subm-edit-chip"
              aria-pressed={(config.cycle_offset ?? 0) === offset}
              onClick={() => onChange({ ...config, cycle_offset: offset })}>
              {cycleOffsetLabel(offset, t)}
            </button>
          ))}
        </div>
      )}
      <span className="field-help">{tChart("cycleHelp")}</span>
    </div>
  );
}
