// Startdaten des Protokoll-Editors verkleinern (Performance-Audit 2026-11-22, L5).
//
// Die Seite lud bisher alle Termine des Mandanten und bis zu 2000 Personen in die Seite (RSC-
// Nutzlast). Hier wählt der Server nur aus, was der Editor zum ersten Darstellen braucht:
//
// - Termine: alle Termine, auf die das Protokoll verweist (IDs in Blöcken, Aufgaben, Listen),
//   alle, die ein Terminfilter eines Blocks treffen kann (gelockert: ohne Zyklus, Limit und
//   Spaltenfilter, also eine Obermenge), und alle ab dem Protokolldatum bzw. heute. Der Rest
//   (ältere Termine für Auswahl, Kalender und Tag-Vorschläge) lädt der Editor nach dem ersten
//   Darstellen nach (useCompleteEvents).
// - Personenverzeichnis: dient nur der Namensauflösung gespeicherter Verweise
//   (participant-directory-context.tsx). Mitgegeben werden nur Personen, deren ID irgendwo in den
//   Startdaten vorkommt, und nur die Felder, die die Anzeige braucht.
import {
  type EventFilter,
  eventMatchesFilter,
  normalizeEventFilter,
} from "@/lib/element-types/event-filter";
import type { EventSummary, ParticipantSummary, ProtocolElement } from "@/types/api";

const UUID_PATTERN = /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/gi;

/** Alle UUIDs, die in den Werten vorkommen (Verweise auf Termine, Personen …). */
export function collectReferencedIds(...values: unknown[]): Set<string> {
  const ids = new Set<string>();
  for (const value of values) {
    if (value == null) continue;
    for (const match of JSON.stringify(value).matchAll(UUID_PATTERN)) ids.add(match[0].toLowerCase());
  }
  return ids;
}

/** Gelockerter Filter: trifft mindestens alles, was der Filter im Editor treffen kann. */
function relaxed(filter: EventFilter): EventFilter {
  return { ...filter, cycle: null, limit: null, use_column_filter: false };
}

/**
 * Alle Terminfilter in den Blockkonfigurationen (rekursiv: Terminliste, «Pro Termin»,
 * Matrix-Automodus, Matrixzeilen, eingebettete Blöcke). Ein Schlüssel ohne Zeitraum gilt als
 * «alle» (die weiteste Vorgabe). ``null``: ein Block braucht alle Termine.
 */
export function protocolEventFilters(elements: ProtocolElement[]): EventFilter[] | null {
  const filters: EventFilter[] = [];
  let needsAll = false;
  const visit = (value: unknown, key: string | null) => {
    if (needsAll || value == null || typeof value !== "object") return;
    if (Array.isArray(value)) {
      value.forEach((item) => visit(item, null));
      return;
    }
    const record = value as Record<string, unknown>;
    if (key !== null && key.endsWith("event_filter")) {
      filters.push(relaxed(normalizeEventFilter(record, "all")));
      return;
    }
    // Matrix-Automodus mit Terminen ohne eigenen Filter: Vorgabe «alle Termine»
    if (key === "auto_source" && record.type === "events" && !record.event_filter) {
      needsAll = true;
      return;
    }
    for (const [childKey, child] of Object.entries(record)) visit(child, childKey);
  };
  for (const element of elements) {
    for (const block of element.blocks) visit(block.configuration_snapshot_json, null);
  }
  return needsAll ? null : filters;
}

/**
 * Termine für den ersten Aufbau des Editors. ``complete``: es fehlt nichts (dann lädt der
 * Editor nichts nach).
 */
export function selectInitialEvents(
  events: EventSummary[],
  options: { elements: ProtocolElement[]; protocolDate: string | null | undefined; today: string; referencedIds: Set<string> },
): { events: EventSummary[]; complete: boolean } {
  const filters = protocolEventFilters(options.elements);
  if (filters === null || !options.protocolDate) return { events, complete: true };
  const protocolDate = options.protocolDate;
  // Kommende Termine (ab Protokolldatum oder heute, was früher ist): Vorgabe «future» der
  // Terminlisten, nächster Hock, fällige Aufgaben.
  const upcomingFrom = protocolDate < options.today ? protocolDate : options.today;
  const context = { protocolDate };
  const selected = events.filter((event) => {
    if (options.referencedIds.has(event.id.toLowerCase())) return true;
    if ((event.event_end_date || event.event_date) >= upcomingFrom) return true;
    return filters.some((filter) => eventMatchesFilter(event, filter, context));
  });
  return { events: selected, complete: selected.length === events.length };
}

/** Personenverzeichnis nur zur Namensauflösung: verwiesene Personen, nur Anzeigefelder. */
export function slimParticipantDirectory(participants: ParticipantSummary[], referencedIds: Set<string>): ParticipantSummary[] {
  return participants
    .filter((participant) => referencedIds.has(participant.id.toLowerCase()))
    .map((participant) => ({
      id: participant.id,
      tenant_id: participant.tenant_id,
      first_name: participant.first_name,
      last_name: participant.last_name,
      display_name: participant.display_name,
      email: null,
      is_active: participant.is_active,
      joined_at: participant.joined_at,
      left_at: participant.left_at,
      created_at: "",
      updated_at: "",
    }));
}
