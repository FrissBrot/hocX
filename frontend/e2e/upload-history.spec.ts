import { test, expect, type APIRequestContext } from "@playwright/test";
import fs from "node:fs/promises";
import path from "node:path";
import { authFiles } from "./auth";
import { uniquePng } from "./unique-fixture";

// Upload-Verlauf (Migration 0250, 1.6): Upload über den Dialog mit einem Duplikat -> Toast
// «Bearbeiten» -> Vorgangsdetail mit Ergebnisliste -> «Alle dieses Uploads auswählen» -> Tag setzen
// -> Aufnahmedatum «früher 1 h 15 min» mit Vorschau (per Tastatur bedient) -> Anwenden -> Zeit im
// Foto-Viewer prüfen -> Rückgängig. Dazu der Verlauf auf Smartphone-Breite.
test.use({ storageState: authFiles.admin });

async function fixture(): Promise<Buffer> {
  return uniquePng(await fs.readFile(path.join("e2e/fixtures/photos/sample.png")));
}

async function waitForIngest(api: APIRequestContext, jobId: string) {
  await expect
    .poll(async () => (await (await api.get(`/api/files/gallery-upload-jobs/${jobId}`)).json()).status, { timeout: 60_000 })
    .toBe("done");
}

test("Upload-Verlauf: Vorgang bearbeiten, Zeit verschieben und rückgängig machen", async ({ page, request }) => {
  test.setTimeout(240_000);
  const stamp = Date.now();
  const tag = `uv-${stamp}`;
  const duplicateBytes = await fixture();
  // Vorhandenes Bild: dieselben Bytes im Dialog ergeben ein Duplikat im Vorgang
  const pre = await request.post("/api/files/gallery-uploads", {
    multipart: { files: { name: `vorher-${stamp}.png`, mimeType: "image/png", buffer: duplicateBytes } },
  });
  expect(pre.ok(), await pre.text()).toBeTruthy();
  await waitForIngest(request, (await pre.json()).id);

  const created: string[] = [];
  try {
    await page.goto("/photos");
    await page.getByRole("button", { name: "Bilder hochladen", exact: true }).click();
    const modal = page.getByRole("dialog", { name: "Bilder hochladen" });
    const chooser = page.waitForEvent("filechooser");
    await modal.getByText("Bilder hierher ziehen").click();
    await (await chooser).setFiles([
      { name: `a-${stamp}.png`, mimeType: "image/png", buffer: await fixture() },
      { name: `b-${stamp}.png`, mimeType: "image/png", buffer: await fixture() },
      { name: `kopie-${stamp}.png`, mimeType: "image/png", buffer: duplicateBytes },
    ]);
    await expect(modal.locator(".gallery-upload-file-list")).toContainText(`kopie-${stamp}.png`);
    const opened = page.waitForResponse((r) => r.url().endsWith("/api/upload-jobs") && r.request().method() === "POST");
    await modal.getByRole("button", { name: "3 Bilder hochladen" }).click();
    const jobId = (await (await opened).json()).id as string;

    // Zusammenfassung nach dem Ingest mit «Bearbeiten»
    const toast = page.locator(".app-toast", { has: page.getByRole("button", { name: "Bearbeiten" }) });
    await expect(toast).toBeVisible({ timeout: 90_000 });
    await toast.getByRole("button", { name: "Bearbeiten" }).click();
    await expect(page).toHaveURL(new RegExp(`/photos/uploads/${jobId}$`));
    await expect(page.getByText("2 hochgeladen · 1 Duplikat")).toBeVisible();

    await page.getByRole("tab", { name: /Ergebnisliste/ }).click();
    await expect(page.getByRole("cell", { name: `kopie-${stamp}.png` })).toBeVisible();
    await expect(page.locator("tr", { hasText: `kopie-${stamp}.png` }).getByText("Duplikat")).toBeVisible();
    await page.getByRole("tab", { name: "Fotos" }).click();

    const ids = (await (await request.get(`/api/upload-jobs/${jobId}/file-ids?only_images=true`)).json()).file_ids as string[];
    expect(ids).toHaveLength(2);
    created.push(...ids);
    // Ausgangszeit mit Uhrzeit setzen (Fixture ohne EXIF)
    const set = await request.post("/api/files/bulk-capture-date", { data: { file_ids: ids, mode: "set", corrected_date: "2026-05-02", corrected_time: "10:00" } });
    expect(set.ok(), await set.text()).toBeTruthy();
    await page.reload();

    await page.getByRole("checkbox", { name: `a-${stamp}.png auswählen` }).click();
    const bar = page.locator(".photo-bulk-bar");
    await bar.getByRole("button", { name: "Alle dieses Uploads auswählen" }).click();
    await expect(bar.getByText("2 Fotos ausgewählt")).toBeVisible();

    // Tag für den ganzen Upload
    await bar.getByRole("button", { name: "Tags" }).click();
    const tagInput = bar.locator(".photo-bulk-bar-tagging input");
    await tagInput.fill(tag);
    await tagInput.press("Enter");
    await bar.getByRole("button", { name: "Anwenden" }).click();
    await expect(page.getByText("Tags hinzugefügt.")).toBeVisible();

    // Zeit verschieben: früher 1 h 15 min, Richtung per Tastatur
    await page.getByRole("checkbox", { name: `a-${stamp}.png auswählen` }).click();
    await bar.getByRole("button", { name: "Alle dieses Uploads auswählen" }).click();
    await bar.getByRole("button", { name: "Aufnahmedatum" }).click();
    const dialog = page.getByRole("dialog", { name: "Aufnahmedatum ändern" });
    await dialog.getByRole("tab", { name: "Verschieben" }).click();
    const later = dialog.getByRole("tab", { name: "Später" });
    await later.focus();
    await page.keyboard.press("ArrowLeft");
    await expect(dialog.getByRole("tab", { name: "Früher" })).toHaveAttribute("aria-selected", "true");
    await dialog.getByLabel("Stunden").fill("1");
    await dialog.getByLabel("Minuten").fill("15");
    await dialog.getByRole("button", { name: "Vorschau" }).click();
    await expect(dialog.getByText("2 Bilder werden geändert.")).toBeVisible();
    await expect(dialog.getByText("02.05.2026 10:00 → 02.05.2026 08:45").first()).toBeVisible();
    await dialog.getByRole("button", { name: "Übernehmen" }).click();
    const applied = page.waitForResponse((r) => r.url().endsWith("/api/files/bulk-capture-date") && r.request().method() === "POST");
    await page.getByRole("alertdialog", { name: "Aufnahmedatum ändern?" }).getByRole("button", { name: "Datum ändern" }).click();
    const result = await (await applied).json();
    expect(result.updated_ids).toHaveLength(2);
    expect(result.batch_id).toBeTruthy();

    const shifted = await (await request.get(`/api/stored-files/${ids[0]}/metadata`)).json();
    expect(shifted.capture_corrected_at).toContain("2026-05-02T08:45");
    expect(shifted.tags).toContain(tag);
    expect(shifted.upload_job.id).toBe(jobId);

    // Foto-Ansicht zeigt die neue Zeit und den Link zum Upload
    if (await bar.count()) await page.locator(".photo-bulk-clear").click();
    await page.locator(".photo-tile", { has: page.getByRole("checkbox", { name: `a-${stamp}.png auswählen` }) }).locator(".photo-tile-preview").click();
    const viewer = page.getByRole("dialog", { name: `a-${stamp}.png` });
    await expect(viewer.getByText(/08:45/).first()).toBeVisible();
    await expect(viewer.getByRole("link", { name: /über Upload mit 2 Dateien/ })).toBeVisible();
    await page.keyboard.press("Escape");

    // Rückgängig im Reiter «Datumskorrekturen»
    await page.getByRole("tab", { name: "Datumskorrekturen" }).click();
    await expect(page.getByText("Verschoben: 1 h 15 min früher")).toBeVisible();
    await page.getByRole("button", { name: "Rückgängig machen" }).click();
    await expect(page.getByText("2 Fotos zurückgesetzt.")).toBeVisible();
    const restored = await (await request.get(`/api/stored-files/${ids[0]}/metadata`)).json();
    expect(restored.capture_corrected_at).toContain("2026-05-02T10:00");

    // Verlauf auf Smartphone-Breite
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/photos/uploads");
    await expect(page.getByRole("heading", { name: "Upload-Verlauf" })).toBeVisible();
    await expect(page.getByRole("link", { name: /\d{2}\.\d{2}\.\d{4}/ }).first()).toBeVisible();
  } finally {
    if (created.length) await request.post("/api/files/bulk-delete", { data: { file_ids: created } }).catch(() => {});
  }
});
