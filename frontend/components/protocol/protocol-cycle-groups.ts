import { ProtocolListCycle, ProtocolSummary } from "@/types/api";

export type ProtocolCycleGroup = {
  key: string;
  /** null = Protokoll ohne Zyklus-Angabe (z. B. gerade erst angelegt). */
  cycle: ProtocolListCycle | null;
  protocols: ProtocolSummary[];
};

const NO_CYCLE_KEY = "none";

/** Gruppiert nach Zyklus (neuester zuerst), innerhalb des Zyklus nach Datum (neuestes zuerst). */
export function groupProtocolsByCycle(protocols: ProtocolSummary[]): ProtocolCycleGroup[] {
  const groups = new Map<string, ProtocolCycleGroup>();
  for (const protocol of protocols) {
    const key = protocol.cycle?.key ?? NO_CYCLE_KEY;
    const group = groups.get(key) ?? { key, cycle: protocol.cycle ?? null, protocols: [] };
    group.protocols.push(protocol);
    groups.set(key, group);
  }
  for (const group of groups.values()) {
    group.protocols.sort((a, b) => (b.protocol_date ?? "").localeCompare(a.protocol_date ?? ""));
  }
  return [...groups.values()].sort((a, b) => {
    if (!a.cycle || !b.cycle) return a.cycle ? 1 : b.cycle ? -1 : 0;
    return b.cycle.start_date.localeCompare(a.cycle.start_date) || (a.cycle.name ?? "").localeCompare(b.cycle.name ?? "");
  });
}

/**
 * Wie viele Gruppen sofort aufgeklappt sind: alles bis und mit dem aktuellen Zyklus (also auch
 * Protokolle in der Zukunft) plus der unmittelbar vorherige Zyklus. Ohne aktuellen Zyklus die
 * zwei neuesten Gruppen. Der Rest steckt hinter "Ältere Zyklen anzeigen".
 */
export function visibleCycleGroupCount(groups: ProtocolCycleGroup[]): number {
  const currentIndex = groups.findIndex((group) => group.cycle?.is_current);
  return Math.min(groups.length, currentIndex >= 0 ? currentIndex + 2 : 2);
}
