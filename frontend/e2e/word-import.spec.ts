import { test, expect } from "@playwright/test";
import { readFile } from "node:fs/promises";
import path from "node:path";
import cases from "./fixtures/word-import/manifest.json";
import { api, seedImport, upload, reanalyze, commitPayload, verifyImported, expectHistoricalRows, fixtureDir, uniqueFixtureFile } from "./word-import.helpers";

test.describe("Word import testbook", () => {
  test.setTimeout(120_000);
  test.use({ actionTimeout: 15_000 });

  for (const fixture of cases.filter((entry) => entry.protocolDate)) {
    test(`IMP-01 ${fixture.file}: date, cycle, archived values and unchanged live list`, async ({ request }) => {
      const seed = await seedImport(request);
      const { documents } = await upload(request, seed, fixture.file);
      expect(documents[0].protocol_date).toBe(fixture.protocolDate);
      const analysis = await reanalyze(request, seed, documents[0].id);
      expect(analysis.protocol_date).toBe(fixture.protocolDate);
      const result = await api(request, "post", `/api/tools/word-import/documents/${documents[0].id}/commit`,
        commitPayload(seed, analysis, fixture.protocolDate!));
      await verifyImported(request, seed, result.id, fixture.protocolDate!, fixture.cycleYear!, fixture.rows);
      await expectHistoricalRows(request, seed, fixture.cycleYear!, fixture.rows);
      const detail = await api(request, "get", `/api/tools/word-import/documents/${documents[0].id}`);
      expect(detail.status).toBe("importiert");
      expect(detail.protocol_id).toBe(result.id);
      expect(detail.protocol_date).toBe(fixture.protocolDate);
    });
  }

  test("IMP-02 direct multipart analysis accepts list UUID overrides", async ({ request }) => {
    const seed = await seedImport(request);
    const response = await request.post("/api/tools/word-import/analyze", { multipart: {
      template_id: seed.template.id,
      table_roles_json: JSON.stringify({ 0: { role: "list", list_definition_id: seed.list.id } }),
      file: { name: "german-date.docx", mimeType: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        buffer: await readFile(path.join(fixtureDir, "german-date.docx")) },
    } });
    expect(response.ok(), await response.text()).toBeTruthy();
    const analysis = await response.json();
    expect(analysis.protocol_date).toBe("2023-10-14");
    expect(analysis.tables[0].list_definition_id).toBe(seed.list.id);
    expect(analysis.list_mappings).toHaveLength(2);
  });

  test("IMP-09 repeated parsing and recovery after a damaged file", async ({ request }) => {
    const seed = await seedImport(request);
    const data = { template_id: seed.template.id,
      table_roles_json: JSON.stringify({ 0: { role: "list", list_definition_id: seed.list.id } }) };
    const invalid = await request.post("/api/tools/word-import/analyze", { multipart: {
      ...data, file: { name: "broken.docx", mimeType: "application/octet-stream", buffer: Buffer.from("not a document") },
    } });
    expect(invalid.status()).toBe(400);
    const buffer = await readFile(path.join(fixtureDir, "leap-day.docx"));
    for (let index = 0; index < 24; index++) {
      const response = await request.post("/api/tools/word-import/analyze", { multipart: {
        ...data, file: { name: "leap-day.docx", mimeType: "application/vnd.openxmlformats-officedocument.wordprocessingml.document", buffer },
      } });
      expect(response.ok(), `Iteration ${index}: ${await response.text()}`).toBeTruthy();
      const analysis = await response.json();
      expect(analysis.protocol_date).toBe("2024-02-29");
      expect(analysis.tables[0].list_definition_id).toBe(seed.list.id);
      expect(analysis.list_mappings.map((row: any) => [row.column_one_raw, row.column_two_raw])).toEqual(cases.find((f) => f.file === "leap-day.docx")!.rows);
    }
  });

  test("IMP-03 corrected date crosses cycle boundary and survives reload/commit", async ({ request }) => {
    const seed = await seedImport(request);
    const { documents } = await upload(request, seed, "cycle-end.docx");
    const analysis = await reanalyze(request, seed, documents[0].id, "2024-08-01");
    expect(analysis.protocol_date).toBe("2024-08-01");
    expect((await api(request, "get", `/api/tools/word-import/documents/${documents[0].id}`)).protocol_date).toBe("2024-08-01");
    const result = await api(request, "post", `/api/tools/word-import/documents/${documents[0].id}/commit`, commitPayload(seed, analysis, "2024-08-01"));
    await verifyImported(request, seed, result.id, "2024-08-01", 2024, cases.find((f) => f.file === "cycle-end.docx")!.rows);
    await expectHistoricalRows(request, seed, 2024, cases.find((f) => f.file === "cycle-end.docx")!.rows);
    expect((await request.get(`/api/table-snapshots/${seed.cycle.id}/2023/list_entry`)).status()).toBe(404);
  });

  test("IMP-04 undated document requires an explicit date", async ({ request }) => {
    const seed = await seedImport(request);
    const { documents } = await upload(request, seed, "no-date.docx");
    expect(documents[0].protocol_date).toBeNull();
    const analysis = await reanalyze(request, seed, documents[0].id);
    expect(analysis.protocol_date).toBeNull();
    const rejected = await request.post(`/api/tools/word-import/documents/${documents[0].id}/commit`, {
      data: { ...commitPayload(seed, analysis, ""), protocol_date: null },
    });
    expect(rejected.status()).toBe(422);
    const corrected = await reanalyze(request, seed, documents[0].id, "2024-02-29");
    const result = await api(request, "post", `/api/tools/word-import/documents/${documents[0].id}/commit`, commitPayload(seed, corrected, "2024-02-29"));
    await verifyImported(request, seed, result.id, "2024-02-29", 2023, cases.find((f) => f.file === "no-date.docx")!.rows);
    await expectHistoricalRows(request, seed, 2023, cases.find((f) => f.file === "no-date.docx")!.rows);
  });

  test("IMP-05 ZIP batch imported out of order keeps dates and snapshots separate", async ({ request }) => {
    const seed = await seedImport(request);
    const result = await upload(request, seed, "historical-batch.zip");
    expect(result.documents).toHaveLength(3);
    expect(result.documents.map((doc: any) => doc.original_filename)).not.toContain("README.txt");
    const imported = [];
    for (const document of result.documents) {
      const fixture = cases.find((f) => f.file === document.original_filename)!;
      expect(fixture).toBeTruthy();
      expect(document.protocol_date).toBe(fixture.protocolDate);
      const analysis = await reanalyze(request, seed, document.id);
      const commit = await api(request, "post", `/api/tools/word-import/documents/${document.id}/commit`, commitPayload(seed, analysis, fixture.protocolDate!));
      imported.push({ id: commit.id, fixture });
    }
    // Read every earlier import again AFTER the last commit to detect overwrites.
    for (const { id, fixture } of imported) await verifyImported(request, seed, id, fixture.protocolDate!, fixture.cycleYear!, fixture.rows);
    expect(new Set(imported.map((entry) => entry.id)).size).toBe(3);
  });

  test("IMP-06 queue commit is not allowed twice", async ({ request }) => {
    const seed = await seedImport(request);
    const { documents } = await upload(request, seed, "german-date.docx");
    const analysis = await reanalyze(request, seed, documents[0].id);
    const payload = commitPayload(seed, analysis, "2023-10-14");
    const url = `/api/tools/word-import/documents/${documents[0].id}/commit`;
    const first = await api(request, "post", url, payload);
    const second = await request.post(url, { data: payload });
    expect(second.ok()).toBeFalsy();
    expect([400, 409]).toContain(second.status());
    expect((await api(request, "get", `/api/tools/word-import/documents/${documents[0].id}`)).protocol_id).toBe(first.id);
  });

  test("IMP-07 browser reanalysis sends list UUIDs and displays the source date", async ({ request, page }) => {
    const seed = await seedImport(request);
    const { documents } = await upload(request, seed, "german-date.docx");
    await reanalyze(request, seed, documents[0].id);
    await page.goto(`/tools/import/${documents[0].id}`);
    await expect(page.getByRole("button", { name: "14.10.2023", exact: true })).toBeVisible();
    const response = page.waitForResponse((r) => r.url().endsWith(`/documents/${documents[0].id}/reanalyze`) && r.request().method() === "POST");
    await page.getByRole("button", { name: "Neu analysieren", exact: true }).click();
    const analyzed = await response;
    expect(analyzed.ok(), await analyzed.text()).toBeTruthy();
    expect(analyzed.request().postDataJSON().table_roles["0"].list_definition_id).toBe(seed.list.id);
    expect((await analyzed.json()).protocol_date).toBe("2023-10-14");
    await expect(page.getByText(/validation error|int_parsing/)).toHaveCount(0);
    await page.reload();
    await expect(page.getByRole("button", { name: "14.10.2023", exact: true })).toBeVisible();
  });

  test("IMP-08 browser upload, date correction, review and commit", async ({ request, page }) => {
    const seed = await seedImport(request);
    await api(request, "put", "/api/tools/word-import/last-template", { template_id: seed.template.id });
    await page.goto("/tools/import");
    const uploaded = page.waitForResponse((r) => r.url().endsWith("/word-import/documents") && r.request().method() === "POST");
    await page.locator('input[type="file"]').setInputFiles(await uniqueFixtureFile("cycle-end.docx"));
    const uploadResponse = await uploaded;
    expect(uploadResponse.ok(), await uploadResponse.text()).toBeTruthy();
    const { documents } = await uploadResponse.json();
    const document = documents[0];
    await reanalyze(request, seed, document.id);
    // Real response, deliberately slow: an empty initial draft must never autosave
    // before hydration (the debounce is 800ms, React StrictMode also runs cleanup).
    let loadingDocument = true;
    const prematureDrafts: unknown[] = [];
    page.on("request", (r) => {
      if (loadingDocument && r.method() === "PUT" && r.url().endsWith(`/documents/${document.id}/draft`)) {
        prematureDrafts.push(r.postDataJSON());
      }
    });
    await page.route(`**/api/tools/word-import/documents/${document.id}`, async (route) => {
      const response = await route.fetch();
      await new Promise((resolve) => setTimeout(resolve, 1100));
      loadingDocument = false;
      await route.fulfill({ response });
    });
    await page.getByRole("row").filter({ hasText: seed.template.name }).getByRole("button", { name: "Prüfen & importieren" }).click();
    await expect(page).toHaveURL(new RegExp(`/tools/import/${document.id}$`));
    await page.getByRole("button", { name: "31.07.2024", exact: true }).click();
    expect(prematureDrafts).toEqual([]);
    await page.getByPlaceholder("dd.mm.yyyy").fill("01.08.2024");
    await page.getByPlaceholder("dd.mm.yyyy").press("Tab");
    const rescanned = page.waitForResponse((r) => r.url().endsWith(`/documents/${document.id}/reanalyze`));
    await page.getByRole("button", { name: "Übernehmen & neu scannen" }).click();
    expect((await rescanned).ok()).toBeTruthy();
    await expect(page.getByRole("button", { name: "01.08.2024", exact: true })).toBeVisible();
    await page.getByRole("button", { name: /Weiter zu den Daten/ }).click();
    await page.getByRole("button", { name: /^Listen/ }).click();
    for (const row of await page.locator(".word-import-text-row").all()) {
      await row.locator(".word-import-text-row-head").click();
      const source = row.getByLabel(/Aus Dokument/);
      if (await source.count()) await source.check();
      const decision = row.locator(".word-import-decision-btn");
      if ((await decision.textContent())?.includes("Unvollständig")) {
        await decision.click(); // explicitly ignore, then approve the reviewed value
        await decision.click();
      }
    }
    const committed = page.waitForResponse((r) => r.url().endsWith(`/documents/${document.id}/commit`));
    await page.getByRole("button", { name: "Protokoll erstellen", exact: true }).click();
    const response = await committed;
    expect(response.ok(), await response.text()).toBeTruthy();
    const { id } = await response.json();
    await verifyImported(request, seed, id, "2024-08-01", 2024, cases.find((f) => f.file === "cycle-end.docx")!.rows);
    await expectHistoricalRows(request, seed, 2024, cases.find((f) => f.file === "cycle-end.docx")!.rows);
  });
});
