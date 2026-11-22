import { describe, expect, it } from "vitest";

import { collectReferencedIds, protocolEventFilters, selectInitialEvents, slimParticipantDirectory } from "./initial-editor-data";
import { mergeEvents } from "./use-complete-events";
import type { EventSummary, ParticipantSummary, ProtocolElement } from "@/types/api";

const id = (n: number) => `0190a000-0000-7000-8000-${String(n).padStart(12, "0")}`;

function event(n: number, date: string, tag = ""): EventSummary {
  return { id: id(n), title: `Termin ${n}`, event_date: date, tag } as EventSummary;
}

function element(configs: Array<Record<string, unknown>>): ProtocolElement {
  return { id: id(900), blocks: configs.map((config, index) => ({ id: id(800 + index), configuration_snapshot_json: config })) } as unknown as ProtocolElement;
}

const EVENTS = [
  event(1, "2024-01-10", "Hock"),
  event(2, "2025-03-01", "Lager"),
  event(3, "2026-10-01", "Hock"),
  event(4, "2026-11-30", ""),
  event(5, "2023-05-05", "Lager"),
];
const BASE = { protocolDate: "2026-11-20", today: "2026-11-21", referencedIds: new Set<string>() };

describe("Startdaten des Protokoll-Editors (L5)", () => {
  it("lässt ohne Terminfilter nur kommende Termine in der Seite", () => {
    const result = selectInitialEvents(EVENTS, { ...BASE, elements: [element([{}])] });
    expect(result.events.map((e) => e.id)).toEqual([id(4)]);
    expect(result.complete).toBe(false);
  });

  it("nimmt verwiesene Termine und alle Treffer gelockerter Filter mit", () => {
    const elements = [
      element([
        // «vergangene Lager» mit Zyklus und Limit: gelockert = alle vergangenen Lager
        { event_filter: { tags: ["lager"], range: { mode: "past" }, cycle: { config_id: null, offset: -1 }, limit: 1 } },
        { rows: [{ row_config: { event_filter: { range: { mode: "window", start_days: -60, end_days: 0 } } } }] },
      ]),
    ];
    const result = selectInitialEvents(EVENTS, { ...BASE, elements, referencedIds: new Set([id(1)]) });
    expect(result.events.map((e) => e.id).sort()).toEqual([id(1), id(2), id(3), id(4), id(5)].sort());
    expect(result.complete).toBe(true);
  });

  it("ein Filter ohne Zeitraum oder ein Matrix-Automodus ohne Filter braucht alle Termine", () => {
    expect(selectInitialEvents(EVENTS, { ...BASE, elements: [element([{ repeat_event_filter: { tags: [] } }])] }).complete).toBe(true);
    expect(protocolEventFilters([element([{ auto_source: { type: "events" } }])])).toBeNull();
    expect(selectInitialEvents(EVENTS, { ...BASE, elements: [element([{ auto_source: { type: "events" } }])] }).events).toBe(EVENTS);
  });

  it("findet Filter in eingebetteten Blöcken", () => {
    const elements = [element([{ columns: [{ embedded: { config: { event_filter: { tags: ["Hock"], range: { mode: "all" } } } } }] }])];
    const result = selectInitialEvents(EVENTS, { ...BASE, elements });
    expect(result.events.map((e) => e.id).sort()).toEqual([id(1), id(3), id(4)].sort());
  });

  it("sammelt UUIDs aus beliebigen Werten", () => {
    const ids = collectReferencedIds({ a: [id(1).toUpperCase()] }, null, `x ${id(2)} y`);
    expect([...ids].sort()).toEqual([id(1), id(2)]);
  });

  it("Personenverzeichnis: nur verwiesene Personen, ohne E-Mail", () => {
    const people = [
      { id: id(10), tenant_id: id(99), display_name: "Andrea", first_name: "A", last_name: "B", email: "a@example.org", is_active: true, joined_at: null, left_at: null, created_at: "x", updated_at: "y" },
      { id: id(11), tenant_id: id(99), display_name: "Benno", first_name: null, last_name: null, email: "b@example.org", is_active: true, joined_at: null, left_at: null, created_at: "x", updated_at: "y" },
    ] as ParticipantSummary[];
    const slim = slimParticipantDirectory(people, new Set([id(10)]));
    expect(slim).toHaveLength(1);
    expect(slim[0]).toMatchObject({ id: id(10), display_name: "Andrea", email: null });
  });

  it("Nachladen: lokaler Stand gewinnt, nichts Neues lässt die Liste unverändert", () => {
    const local = { ...event(4, "2026-12-01"), title: "lokal geändert" } as EventSummary;
    const created = event(6, "2027-01-01");
    const merged = mergeEvents([local, created], EVENTS);
    expect(merged.find((e) => e.id === id(4))?.title).toBe("lokal geändert");
    expect(merged.map((e) => e.id)).toEqual([id(1), id(2), id(3), id(4), id(5), id(6)]);
    const same = [event(1, "2024-01-10")];
    expect(mergeEvents(same, [event(1, "2024-01-10")])).toBe(same);
  });
});
