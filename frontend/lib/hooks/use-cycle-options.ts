"use client";
import { useEffect, useState } from "react";
import { browserApiFetch } from "@/lib/api/client";
import type { CycleConfigSummary, CycleInfo } from "@/types/api";

export type CycleOption = CycleInfo & { cycle_config_id: string; config_name: string };

/** Lädt alle Zyklus-Definitionen samt ihrer wählbaren Zyklen (für Zyklus-Chips an Terminen). */
export function useCycleOptions() {
  const [options, setOptions] = useState<CycleOption[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const configs = (await browserApiFetch<CycleConfigSummary[]>("/api/cycle-configs")) ?? [];
        const groups = await Promise.all(
          configs.map((config) =>
            browserApiFetch<CycleInfo[]>(`/api/cycle-configs/${config.id}/cycles`)
              .then((cycles) => (cycles ?? []).map((cycle) => ({ ...cycle, cycle_config_id: config.id, config_name: config.name })))
              .catch(() => [] as CycleOption[])
          )
        );
        if (!cancelled) setOptions(groups.flat());
      } catch {
        if (!cancelled) setOptions([]);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  return { options, loading };
}
