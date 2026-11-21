import { test, expect, type APIRequestContext } from "@playwright/test";
import fs from "node:fs/promises";
import path from "node:path";
import { authFiles } from "./auth";
import { uniquePng } from "./unique-fixture";

// Keywords und Synonyme (Migration 0217): Keyword in der Foto-Ansicht setzen (Tastatur: Enter),
// danach findet die Suche das Bild mit Tippfehler und über ein eigenes Synonym des Vereins.
test.use({ storageState: authFiles.admin });

async function uploadPhoto(api: APIRequestContext, name: string): Promise<string> {
  const buffer = uniquePng(await fs.readFile(path.join("e2e/fixtures/photos/sample.png")));
  const response = await api.post("/api/files/gallery-uploads", { multipart: { files: { name, mimeType: "image/png", buffer } } });
  expect(response.ok(), await response.text()).toBeTruthy();
  const job = await response.json();
  await expect
    .poll(async () => (await (await api.get(`/api/files/gallery-upload-jobs/${job.id}`)).json()).status, { timeout: 60_000 })
    .toBe("done");
  const detail = await (await api.get(`/api/files/gallery-upload-jobs/${job.id}`)).json();
  return detail.imported_items[0].id as string;
}

function letters(length: number): string {
  const alphabet = "bcdfghjklmnpqrstvwxz";
  return Array.from({ length }, () => alphabet[Math.floor(Math.random() * alphabet.length)]).join("");
}

test("Keyword setzen, dann mit Tippfehler und Synonym finden", async ({ page, request }) => {
  test.setTimeout(180_000);
  const suffix = letters(6);
  const name = `keyword-${Date.now()}.png`;
  const keyword = `Gipfelkreuz${suffix}`;
  const synonym = `Bergspitz${suffix}`;
  const fileId = await uploadPhoto(request, name);
  const before = await (await request.get("/api/search-synonyms")).json();
  try {
    await page.goto("/photos");
    const search = page.getByPlaceholder(/^Suchen nach Name, Tag/);
    await search.fill(name);
    const select = page.getByRole("checkbox", { name: `${name} auswählen` });
    await expect(select).toBeVisible();
    await page.locator(".photo-tile", { has: select }).locator(".photo-tile-preview").click();

    const viewer = page.getByRole("dialog", { name });
    const input = viewer.getByRole("textbox", { name: "Keywords" });
    await input.click();
    await input.fill(keyword);
    const saved = page.waitForResponse((r) => r.url().endsWith(`/api/stored-files/${fileId}/keywords`) && r.request().method() === "PATCH");
    await input.press("Enter");
    expect((await saved).ok()).toBeTruthy();
    await expect(viewer.locator(".keyword-chip", { hasText: keyword })).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(viewer).toHaveCount(0);

    // Tippfehler: ein Buchstabe fehlt
    await search.fill(`Gipfelkruz${suffix}`);
    await expect(page.getByRole("checkbox", { name: `${name} auswählen` })).toBeVisible();

    // Eigenes Synonym des Vereins
    const put = await request.put("/api/search-synonyms", { data: { groups: [...before.groups, [synonym, keyword]] } });
    expect(put.ok(), await put.text()).toBeTruthy();
    await search.fill(synonym.toLowerCase());
    await expect(page.getByRole("checkbox", { name: `${name} auswählen` })).toBeVisible();
    await search.fill(`zzz${letters(8)}`);
    await expect(page.getByRole("checkbox", { name: `${name} auswählen` })).toHaveCount(0);
  } finally {
    await request.put("/api/search-synonyms", { data: { groups: before.groups ?? [] } }).catch(() => {});
    await request.post("/api/files/bulk-delete", { data: { file_ids: [fileId] } }).catch(() => {});
  }
});
