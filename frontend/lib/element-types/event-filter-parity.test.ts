import { readFileSync } from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

import { applyEventFilter, normalizeEventFilter } from "./event-filter";

// Terminfilter: Editor und PDF wählen dieselben Termine in derselben Reihenfolge. Das PDF filtert
// in Python (backend/app/services/event_filter.py); beide prüfen denselben Katalog
// (backend/tests/test_event_filter_parity.py). Sonst stünden im PDF Termine, die im Editor
// weggefiltert sind.
const CORPUS_PATH = path.resolve(__dirname, "../../../backend/tests/fixtures/event_filter_parity.json");

type CorpusEvent = { id: number; uuid: string; event_date: string; event_end_date: string | null; title: string; tag: string | null; description: string | null };
type CorpusCase = { name: string; filter: unknown; column: { title?: string; event_tag_filter?: string } | null; expected: number[] };
const corpus = JSON.parse(readFileSync(CORPUS_PATH, "utf8")) as { protocol_date: string; events: CorpusEvent[]; cases: CorpusCase[] };

const events = corpus.events.map((event) => ({ ...event, id: event.uuid }));
const internalId = new Map(corpus.events.map((event) => [event.uuid, event.id]));

describe("Terminfilter wie im PDF", () => {
  it.each(corpus.cases)("$name", ({ filter, column, expected }) => {
    const result = applyEventFilter(events, normalizeEventFilter(filter, "all"), { protocolDate: corpus.protocol_date, column });
    expect(result.map((event) => internalId.get(event.id))).toEqual(expected);
  });
});
