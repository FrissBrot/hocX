import { expect, type APIRequestContext } from "@playwright/test";
import { readFile } from "node:fs/promises";
import path from "node:path";

export const fixtureDir = path.resolve("e2e/fixtures/word-import");
export const uuidPattern = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
export async function api(request: APIRequestContext, method: "get" | "post" | "patch" | "put", url: string, data?: unknown) {
  const response = await request[method](url, data === undefined ? {} : { data });
  expect(response.ok(), `${method} ${url}: ${await response.text()}`).toBeTruthy();
  return response.json();
}

export async function seedImport(request: APIRequestContext) {
  const suffix = `${Date.now()}-${Math.random().toString(16).slice(2, 8)}`;
  const cycle = await api(request, "post", "/api/cycle-configs", { name: `Import E2E ${suffix}`, reset_month: 7, reset_day: 31 });
  const list = await api(request, "post", "/api/lists", {
    name: `E2E Historische Aufgaben ${suffix}`, column_one_title: "Aufgabe", column_one_value_type: "text",
    column_two_title: "Wert", column_two_value_type: "text",
  });
  const entries = [];
  for (const task of ["Feuer", "Küche"]) {
    entries.push(await api(request, "post", `/api/lists/${list.id}/entries`, {
      sort_index: (entries.length + 1) * 10,
      column_one_value: { text_value: task }, column_two_value: { text_value: "LIVE HEUTE" },
    }));
  }
  const template = await api(request, "post", "/api/templates", {
    name: `Import E2E ${suffix}`, cycle_config_id: cycle.id, protocol_number_pattern: "E2E-{n}",
    title_pattern: "{n}. Hock vom {dd.mm.yyyy}", auto_create_next_protocol: false,
  });
  const definition = await api(request, "post", "/api/element-definitions", {
    title: "E2E Historische Aufgaben", blocks: [{
      id: 1, title: "E2E Historische Aufgaben", element_type_id: 6, render_type_id: 5,
      sort_index: 10, configuration_json: { linked_list_id: list.id },
    }],
  });
  await api(request, "post", `/api/templates/${template.id}/elements`, { element_definition_id: definition.id, sort_index: 10 });
  for (const id of [cycle.id, list.id, template.id, definition.id, ...entries.map((entry) => entry.id)]) expect(id).toMatch(uuidPattern);
  return { cycle, list, template, entries };
}
export type ImportSeed = Awaited<ReturnType<typeof seedImport>>;

export async function historicalRows(request: APIRequestContext, seed: ImportSeed, year: number) {
  const base = `/api/table-snapshots/${seed.cycle.id}/${year}`;
  const definitions = await api(request, "get", `${base}/list_definition`);
  const definition = definitions.rows.find((row: any) => row.public_id === seed.list.id);
  expect(definition).toBeTruthy();
  const entries = await api(request, "get", `${base}/list_entry`);
  return entries.rows.filter((row: any) => row.list_definition_id === definition.id)
    .sort((a: any, b: any) => a.sort_index - b.sort_index);
}

export async function expectHistoricalRows(request: APIRequestContext, seed: ImportSeed, year: number, expected: string[][]) {
  const rows = await historicalRows(request, seed, year);
  expect(rows.map((row: any) => [row.column_one_value_json.text_value, row.column_two_value_json.text_value])).toEqual(expected);
  for (const row of rows) expect(row.public_id).toMatch(uuidPattern);
  return rows;
}

export async function upload(request: APIRequestContext, seed: ImportSeed, filename: string) {
  const response = await request.post("/api/tools/word-import/documents", { multipart: {
    template_id: seed.template.id,
    files: { name: filename, mimeType: filename.endsWith(".zip") ? "application/zip" : "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
      buffer: await readFile(path.join(fixtureDir, filename)) },
  } });
  expect(response.ok(), await response.text()).toBeTruthy();
  const result = await response.json();
  if (!filename.endsWith(".zip")) expect(result.errors).toEqual([]);
  expect(result.documents.length).toBeGreaterThan(0);
  return result;
}

export async function reanalyze(request: APIRequestContext, seed: ImportSeed, documentId: string, protocolDate?: string) {
  const analysis = await api(request, "post", `/api/tools/word-import/documents/${documentId}/reanalyze`, {
    protocol_date: protocolDate ?? null,
    table_roles: { 0: { role: "list", list_definition_id: seed.list.id, list_grouping_strategy: "flat" } },
  });
  expect(analysis.tables[0].list_definition_id).toBe(seed.list.id);
  expect(analysis.list_mappings).toHaveLength(2);
  return analysis;
}

export function commitPayload(seed: ImportSeed, analysis: any, protocolDate: string) {
  return {
    template_id: seed.template.id, protocol_date: protocolDate,
    lists: analysis.list_mappings.map((row: any) => ({
      table_index: row.table_index, list_definition_id: seed.list.id, approved: true,
      column_one_raw: row.column_one_raw, column_two_raw: row.column_two_raw,
      linked_entry_id: seed.entries.find((entry) => entry.column_one_value.text_value === row.column_one_raw)?.id ?? null,
    })),
    tables: [{ header_signature: "aufgabe|wert", role: "list", list_definition_id: seed.list.id, list_grouping_strategy: "flat" }],
  };
}

export async function verifyImported(request: APIRequestContext, seed: ImportSeed, protocolId: string, expectedDate: string,
  expectedCycle: number, expectedRows: string[][]) {
  expect(protocolId).toMatch(uuidPattern);
  const protocol = await api(request, "get", `/api/protocols/${protocolId}`);
  expect(protocol.protocol_date).toBe(expectedDate);
  expect(protocol.status).toBe("abgeschlossen");
  const [year, month, day] = expectedDate.split("-");
  expect(protocol.title).toContain(`${day}.${month}.${year}`);
  const cycle = await api(request, "get", `/api/protocols/${protocolId}/cycle-events`);
  expect(cycle.cycle.cycle_year).toBe(expectedCycle);
  expect(cycle.cycle.cycle_config_id).toBe(seed.cycle.id);
  const elements = await api(request, "get", `/api/protocols/${protocolId}/elements`);
  const block = elements.flatMap((element: any) => element.blocks).find((item: any) => item.configuration_snapshot_json.list_snapshot);
  expect(block).toBeTruthy();
  const rows = block.configuration_snapshot_json.list_snapshot.entries;
  expect(rows.map((row: any) => [row.column_one_value.text_value, row.column_two_value.text_value])).toEqual(expectedRows);
  expect(await api(request, "get", `/api/lists/${seed.list.id}/entries`)).toEqual(seed.entries);
  return { protocol, rows, block };
}
