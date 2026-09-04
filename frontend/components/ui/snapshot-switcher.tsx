"use client";

import { TableSnapshotCycleSummary } from "@/types/api";

type SnapshotSwitcherProps = {
  mode: "live" | "historical";
  availableCycles: TableSnapshotCycleSummary[];
  cycleConfigId: string | null;
  cycleYear: number | null;
  onSwitchToLive: () => void;
  onSwitchToHistorical: (cycleConfigId: string, cycleYear: number) => void;
};

/** Dropdown for switching a table overview between the live, editable view and a
 * frozen cycle snapshot - meant to be dropped into a page's existing toolbar/actions
 * row (see components/ui/data-table.tsx's DataToolbar `actions` slot, or wherever a
 * given manager already renders its own action buttons). Renders nothing if the tenant
 * has no historical snapshots for this table yet. */
export function SnapshotSwitcher({ mode, availableCycles, cycleConfigId, cycleYear, onSwitchToLive, onSwitchToHistorical }: SnapshotSwitcherProps) {
  if (availableCycles.length === 0) {
    return null;
  }

  const currentValue = mode === "historical" && cycleConfigId && cycleYear !== null ? `${cycleConfigId}:${cycleYear}` : "live";

  return (
    <label className="field-stack snapshot-switcher">
      <span className="field-label">Ansicht</span>
      <select
        value={currentValue}
        onChange={(event) => {
          const value = event.target.value;
          if (value === "live") {
            onSwitchToLive();
            return;
          }
          const [id, yearRaw] = value.split(":");
          onSwitchToHistorical(id, Number(yearRaw));
        }}
      >
        <option value="live">Aktuell (bearbeitbar)</option>
        {availableCycles.map((cycle) => (
          <option key={`${cycle.cycle_config_id}:${cycle.cycle_year}`} value={`${cycle.cycle_config_id}:${cycle.cycle_year}`}>
            {cycle.cycle_config_name} {cycle.cycle_year} (historisch)
          </option>
        ))}
      </select>
    </label>
  );
}
