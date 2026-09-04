"use client";

import { TableSnapshotCycleSummary } from "@/types/api";

type SnapshotSwitcherProps = {
  mode: "live" | "historical" | "reconstructing";
  availableCycles: TableSnapshotCycleSummary[];
  cycleConfigId: string | null;
  cycleYear: number | null;
  onSwitchToLive: () => void;
  onSwitchToHistorical: (cycleConfigId: string, cycleYear: number, hasSnapshot: boolean) => void;
};

/** Dropdown for switching a table overview between the live, editable view and a
 * cycle's snapshot - meant to be dropped into a page's existing toolbar/actions row
 * (see components/ui/data-table.tsx's DataToolbar `actions` slot, or wherever a given
 * manager already renders its own action buttons). Renders nothing if the tenant has no
 * relevant cycles at all yet. A period with has_snapshot=false (a real, ended period
 * with no snapshot - a gap) is listed with a warning marker; selecting it starts
 * reconstruction instead of a normal read-only view. */
export function SnapshotSwitcher({ mode, availableCycles, cycleConfigId, cycleYear, onSwitchToLive, onSwitchToHistorical }: SnapshotSwitcherProps) {
  if (availableCycles.length === 0) {
    return null;
  }

  // Must match an <option value> exactly (including the has_snapshot suffix) or the
  // browser silently falls back to the first option - looked up from availableCycles
  // rather than assumed, so it stays correct even mid-reconstruction (has_snapshot
  // still false there) and right after confirming (has_snapshot flips true once
  // availableCycles is refetched).
  const selectedCycle =
    mode !== "live" && cycleConfigId && cycleYear !== null
      ? availableCycles.find((c) => c.cycle_config_id === cycleConfigId && c.cycle_year === cycleYear)
      : null;
  const currentValue = selectedCycle
    ? `${selectedCycle.cycle_config_id}:${selectedCycle.cycle_year}:${selectedCycle.has_snapshot ? "1" : "0"}`
    : "live";

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
          const [id, yearRaw, hasSnapshotRaw] = value.split(":");
          onSwitchToHistorical(id, Number(yearRaw), hasSnapshotRaw === "1");
        }}
      >
        <option value="live">Aktuell (bearbeitbar)</option>
        {availableCycles.map((cycle) => (
          <option
            key={`${cycle.cycle_config_id}:${cycle.cycle_year}`}
            value={`${cycle.cycle_config_id}:${cycle.cycle_year}:${cycle.has_snapshot ? "1" : "0"}`}
          >
            {cycle.has_snapshot
              ? `${cycle.cycle_config_name} ${cycle.cycle_year} (historisch)`
              : `⚠ ${cycle.cycle_config_name} ${cycle.cycle_year} (kein Snapshot)`}
          </option>
        ))}
      </select>
    </label>
  );
}
