import { test, expect, type APIRequestContext } from "@playwright/test";
import fs from "node:fs/promises";
import path from "node:path";
import { authFiles } from "./auth";
import { uniquePng } from "./unique-fixture";

// Korrigiertes Aufnahmedatum (Migration 0200): Mehrfachauswahl der Galerie «Aufnahmedatum» ->
// Dialog -> Bestätigung mit Hinweis -> POST /api/files/bulk-capture-date. Danach Einzelbearbeitung
// im Foto-Viewer: «Original wiederherstellen» entfernt die Korrektur wieder.
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

test("Aufnahmedatum per Mehrfachauswahl korrigieren und im Viewer wiederherstellen", async ({ page, request }) => {
  test.setTimeout(180_000);
  const name = `aufnahme-${Date.now()}.png`;
  const fileId = await uploadPhoto(request, name);
  try {
    await page.goto("/photos");
    // Gemeinsamer E2E-Mandant: auf das eigene Bild filtern (bleibt nach dem Neuladen bestehen)
    await page.getByPlaceholder("Fotos durchsuchen").fill(name);
    const select = page.getByRole("checkbox", { name: `${name} auswählen` });
    await select.click();
    await page.locator(".photo-bulk-bar").getByRole("button", { name: "Aufnahmedatum" }).click();

    const dialog = page.getByRole("dialog", { name: "Aufnahmedatum ändern" });
    await expect(dialog.getByText("Gilt für 1 ausgewähltes Bild.")).toBeVisible();
    const date = dialog.getByLabel("Datum", { exact: true });
    await date.fill("05.06.2001");
    await date.blur();
    const time = dialog.getByLabel("Uhrzeit (optional)");
    await time.fill("1430");
    await time.blur();
    await dialog.getByRole("button", { name: "Übernehmen" }).click();

    const confirm = page.getByRole("alertdialog", { name: "Aufnahmedatum ändern?" });
    await expect(confirm).toContainText("Das Aufnahmedatum von 1 Bild wird auf 05.06.2001, 14:30 gesetzt.");
    await expect(confirm).toContainText("Reihenfolge im Zeitstrahl");
    await expect(confirm).toContainText("bleibt erhalten");
    const saved = page.waitForResponse((r) => r.url().endsWith("/api/files/bulk-capture-date") && r.request().method() === "POST");
    await confirm.getByRole("button", { name: "Datum ändern" }).click();
    const response = await saved;
    expect(response.ok(), await response.text()).toBeTruthy();
    expect((await response.json()).updated_ids).toEqual([fileId]);
    await expect(page.getByText("Aufnahmedatum von 1 Bild geändert.")).toBeVisible();

    const metadata = await (await request.get(`/api/stored-files/${fileId}/metadata`)).json();
    expect(metadata.date_source).toBe("corrected");
    expect(metadata.effective_date).toBe("2001-06-05");
    expect(metadata.capture_corrected_has_time).toBe(true);

    // Einzelbearbeitung: im Viewer wieder auf das Original zurück (Datei hat kein EXIF -> Upload)
    if (await page.locator(".photo-bulk-bar").count()) await page.locator(".photo-bulk-clear").click();
    await expect(page.locator(".photo-bulk-bar")).toHaveCount(0);
    await page.locator(".photo-tile", { has: select }).locator(".photo-tile-preview").click();
    const viewer = page.getByRole("dialog", { name });
    await expect(viewer.getByText("Aufnahmedatum · korrigiert")).toBeVisible();
    await expect(viewer.getByText("Die Datei enthält kein Aufnahmedatum.")).toBeVisible();
    await viewer.getByRole("button", { name: "Ändern" }).click();
    await viewer.getByRole("button", { name: "Original wiederherstellen" }).click();
    const resetConfirm = page.getByRole("alertdialog", { name: "Aufnahmedatum ändern?" });
    await expect(resetConfirm).toContainText("Bei 1 Bild wird die Korrektur entfernt");
    const reset = page.waitForResponse((r) => r.url().endsWith(`/api/stored-files/${fileId}/capture-correction`) && r.request().method() === "PATCH");
    await resetConfirm.getByRole("button", { name: "Datum ändern" }).click();
    expect((await reset).ok()).toBeTruthy();
    await expect(viewer.getByText("Aufnahmedatum unbekannt")).toBeVisible();
    const after = await (await request.get(`/api/stored-files/${fileId}/metadata`)).json();
    expect(after.date_source).toBe("upload");
    expect(after.capture_corrected_at).toBeNull();
  } finally {
    await request.post("/api/files/bulk-delete", { data: { file_ids: [fileId] } }).catch(() => {});
  }
});
