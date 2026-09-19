import { test, expect, type Page } from "@playwright/test";
import cases from "./fixtures/word-import/manifest.json";
import { api, seedImport, upload, reanalyze, commitPayload, expectHistoricalRows, type ImportSeed } from "./word-import.helpers";
import { authFiles } from "./auth";

async function importFile(request: any, seed: ImportSeed, filename: string, overrideDate?: string) {
  const fixture = cases.find((entry) => entry.file === filename)!;
  const { documents } = await upload(request, seed, filename);
  const analysis = await reanalyze(request, seed, documents[0].id, overrideDate);
  return api(request, "post", `/api/tools/word-import/documents/${documents[0].id}/commit`,
    commitPayload(seed, analysis, overrideDate ?? fixture.protocolDate!));
}

// The list sidebar button's accessible name is "<name> <n> Einträge" (name + entry-count
// spans), so it can't be matched exactly by name alone, and the "Ansicht" picker is a
// SearchableSelect (button + listbox), not a native <select>.
async function openHistoricalView(page: Page, seed: ImportSeed) {
  await page.getByRole("button", { name: seed.list.name }).click();
  await page.getByRole("button", { name: "Ansicht", exact: true }).click();
  await page.getByRole("option", { name: `${seed.cycle.name} 2023 (historisch)` }).click();
}

test.describe("Historical list import testbook", () => {
  test.setTimeout(120_000);
  test.use({ actionTimeout: 15_000 });
  for (const order of [["leap-day.docx", "cycle-end.docx"], ["cycle-end.docx", "leap-day.docx"]]) {
    test(`HIST-01 newest source date wins: ${order.join(" then ")}`, async ({ request }) => {
      const seed = await seedImport(request);
      for (const file of order) await importFile(request, seed, file);
      await expectHistoricalRows(request, seed, 2023, cases.find((entry) => entry.file === "cycle-end.docx")!.rows);
      await importFile(request, seed, "cycle-start.docx");
      await expectHistoricalRows(request, seed, 2023, cases.find((entry) => entry.file === "cycle-end.docx")!.rows);
      await expectHistoricalRows(request, seed, 2024, cases.find((entry) => entry.file === "cycle-start.docx")!.rows);
      expect(await api(request, "get", `/api/lists/${seed.list.id}/entries`)).toEqual(seed.entries);
    });
  }

  test("HIST-02 human-edited historical values survive a newer import", async ({ request }) => {
    const seed = await seedImport(request);
    await importFile(request, seed, "leap-day.docx");
    const rows = await expectHistoricalRows(request, seed, 2023, cases.find((entry) => entry.file === "leap-day.docx")!.rows);
    const url = `/api/table-snapshots/${seed.cycle.id}/2023/list_entry/rows/${rows[0].public_id}`;
    const data = { values: { column_two_value_json: { text_value: "MANUELL GEPRÜFT" } } };
    expect((await request.put(url, { data })).status()).toBe(400);
    await api(request, "put", url, { ...data, confirm_historical_edit: true });
    await importFile(request, seed, "cycle-end.docx");
    await expectHistoricalRows(request, seed, 2023, [["Feuer", "MANUELL GEPRÜFT"], ["Küche", "Menü – Schalttag 2024"]]);
  });

  test("HIST-03 pre-existing reconstructed historical state is protected", async ({ request }) => {
    const seed = await seedImport(request);
    const base = `/api/table-snapshots/${seed.cycle.id}/2023/lists/${seed.list.id}`;
    const draft = await api(request, "get", `${base}/reconstruct-draft`);
    const response = await request.post(`${base}/reconstruct`, { data: {
      definition_values: draft.definition_values,
      entries: draft.entries.map((row: any) => ({ ...row, column_two_value_json: { text_value: "BESTEHENDE HISTORIE" } })),
    } });
    expect(response.ok(), await response.text()).toBeTruthy();
    await importFile(request, seed, "cycle-end.docx");
    await expectHistoricalRows(request, seed, 2023, [["Feuer", "BESTEHENDE HISTORIE"], ["Küche", "BESTEHENDE HISTORIE"]]);
  });

  test("HIST-04 snapshot-only imported rows receive stable identities without live entries", async ({ request }) => {
    const seed = await seedImport(request);
    const { documents } = await upload(request, seed, "leap-day.docx");
    const analysis = await reanalyze(request, seed, documents[0].id);
    const payload = commitPayload(seed, analysis, "2024-02-29");
    payload.lists = payload.lists.map((row: any) => ({ ...row, linked_entry_id: null }));
    await api(request, "post", `/api/tools/word-import/documents/${documents[0].id}/commit`, payload);
    const rows = await expectHistoricalRows(request, seed, 2023, cases.find((entry) => entry.file === "leap-day.docx")!.rows);
    expect(rows.every((row: any) => row.id < 0)).toBeTruthy();
    expect(new Set(rows.map((row: any) => row.public_id)).size).toBe(2);
    expect(await expectHistoricalRows(request, seed, 2023, cases.find((entry) => entry.file === "leap-day.docx")!.rows)).toEqual(rows);
    expect(await api(request, "get", `/api/lists/${seed.list.id}/entries`)).toEqual(seed.entries);
  });

  test("HIST-05 current and future imports do not create historical cycles", async ({ request }) => {
    const seed = await seedImport(request);
    const now = new Date();
    const today = now.toISOString().slice(0, 10);
    const currentCycle = now.getUTCFullYear() - (today.slice(5) <= "07-31" ? 1 : 0);
    for (const [date, year] of [[today, currentCycle], ["2100-08-01", 2100]] as const) {
      await importFile(request, seed, "german-date.docx", date);
      expect((await request.get(`/api/table-snapshots/${seed.cycle.id}/${year}/list_entry`)).status()).toBe(404);
    }
  });

  test("HIST-06 historical list is visible in browser after reload and isolated by tenant", async ({ request, page, browser }) => {
    const seed = await seedImport(request);
    await importFile(request, seed, "leap-day.docx");
    await page.goto("/lists");
    await openHistoricalView(page, seed);
    await expect(page.getByText("Schalttag 2024", { exact: true })).toBeVisible();
    await expect(page.getByText("Menü – Schalttag 2024", { exact: true })).toBeVisible();
    await expect(page.getByText("LIVE HEUTE", { exact: true })).toHaveCount(0);
    await page.reload();
    await openHistoricalView(page, seed);
    await expect(page.getByText("Schalttag 2024", { exact: true })).toBeVisible();
    const other = await browser.newContext({ storageState: authFiles.tenantTwo });
    try {
      expect((await other.request.get(`/api/table-snapshots/${seed.cycle.id}/2023/list_entry`)).status()).toBe(404);
    } finally { await other.close(); }
  });
});
