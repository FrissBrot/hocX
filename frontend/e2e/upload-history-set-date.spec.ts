import { test, expect, type APIRequestContext } from "@playwright/test";
import fs from "node:fs/promises";
import path from "node:path";
import { authFiles } from "./auth";
import { uniquePng } from "./unique-fixture";

// Upload-Verlauf (1.6), Aktion «Datum setzen»: im Vorgangsdetail alle Fotos des Uploads auf ein
// festes Datum mit Uhrzeit setzen (Datum/Uhrzeit per Tastatur), Vorschau, Anwenden, Eintrag im
// Reiter «Datumskorrekturen» mit dem gesetzten Wert, Rückgängig. Dazu die Auswahl einzelner Dateien
// in der Ergebnisliste und der Kopf auf Smartphone-Breite.
test.use({ storageState: authFiles.admin });

async function fixture(): Promise<Buffer> {
  return uniquePng(await fs.readFile(path.join("e2e/fixtures/photos/sample.png")));
}

async function uploadJobWithTwoPhotos(api: APIRequestContext, stamp: number): Promise<string> {
  const response = await api.post("/api/files/gallery-uploads", {
    multipart: {
      files: { name: `datum-a-${stamp}.png`, mimeType: "image/png", buffer: await fixture() },
    },
  });
  expect(response.ok(), await response.text()).toBeTruthy();
  const ingest = (await response.json()).id as string;
  let uploadJobId = "";
  await expect
    .poll(async () => {
      const job = await (await api.get(`/api/files/gallery-upload-jobs/${ingest}`)).json();
      uploadJobId = job.upload_job_id ?? "";
      return job.status;
    }, { timeout: 60_000 })
    .toBe("done");
  expect(uploadJobId).toBeTruthy();
  return uploadJobId;
}

test("Upload-Verlauf: «Datum setzen» für alle Fotos eines Vorgangs, Auswahl und Rückgängig", async ({ page, request }) => {
  test.setTimeout(180_000);
  const stamp = Date.now();
  const jobId = await uploadJobWithTwoPhotos(request, stamp);
  const ids = (await (await request.get(`/api/upload-jobs/${jobId}/file-ids?only_images=true`)).json()).file_ids as string[];
  expect(ids).toHaveLength(1);
  try {
    await page.goto(`/photos/uploads/${jobId}`);
    await expect(page.getByRole("heading", { name: /Upload vom/ })).toBeVisible();

    // Kopf-Aktion: alle Fotos des Uploads, Dialog startet im Modus «Auf Datum setzen»
    await page.locator(".page-header").getByRole("button", { name: "Datum setzen …" }).click();
    const dialog = page.getByRole("dialog", { name: "Aufnahmedatum ändern" });
    await expect(dialog.getByText("Gilt für 1 ausgewähltes Bild.")).toBeVisible();
    await expect(dialog.getByRole("tab", { name: "Auf Datum setzen" })).toHaveAttribute("aria-selected", "true");

    // Datum und Uhrzeit per Tastatur (Kurzformen werden korrigiert: 1430 → 14:30)
    await dialog.getByRole("textbox", { name: "Datum", exact: true }).focus();
    await page.keyboard.type("02.05.2026");
    await page.keyboard.press("Tab"); // Kalender-Knopf des Datumsfelds
    await page.keyboard.press("Tab");
    await expect(dialog.getByRole("textbox", { name: "Uhrzeit (optional)", exact: true })).toBeFocused();
    await page.keyboard.type("1430");
    await page.keyboard.press("Tab");
    await dialog.getByRole("button", { name: "Vorschau" }).click();
    await expect(dialog.getByText("1 Bild wird geändert.")).toBeVisible();
    await expect(dialog.getByText(/→ 02\.05\.2026 14:30/).first()).toBeVisible();

    const applied = page.waitForResponse((r) => r.url().endsWith("/api/files/bulk-capture-date") && r.request().method() === "POST");
    await dialog.getByRole("button", { name: "Übernehmen" }).click();
    await page.getByRole("alertdialog", { name: "Aufnahmedatum ändern?" }).getByRole("button", { name: "Datum ändern" }).click();
    const result = await (await applied).json();
    expect(result.updated_ids).toHaveLength(1);
    expect(result.batch_id).toBeTruthy();
    const after = await (await request.get(`/api/stored-files/${ids[0]}/metadata`)).json();
    expect(after.capture_corrected_at).toContain("2026-05-02T14:30");

    // Reiter «Datumskorrekturen»: Eintrag mit dem gesetzten Wert, Rückgängig
    await page.getByRole("tab", { name: "Datumskorrekturen" }).click();
    await expect(page.getByText("Auf 02.05.2026 14:30 gesetzt")).toBeVisible();
    await page.getByRole("button", { name: "Rückgängig machen" }).click();
    await expect(page.getByText("1 Foto zurückgesetzt.")).toBeVisible();
    const restored = await (await request.get(`/api/stored-files/${ids[0]}/metadata`)).json();
    expect(restored.capture_corrected_at).toBeNull();

    // Ergebnisliste: einzelne Datei auswählen und nur für sie ein Datum (ohne Uhrzeit) setzen
    await page.getByRole("tab", { name: /Ergebnisliste/ }).click();
    const checkbox = page.getByRole("checkbox", { name: `«datum-a-${stamp}.png» auswählen` });
    await checkbox.focus();
    await page.keyboard.press("Space");
    const toolbar = page.locator(".table-toolbar", { hasText: "1 Datei ausgewählt" });
    await expect(toolbar).toBeVisible();
    await toolbar.getByRole("button", { name: "Datum setzen …" }).click();
    const selectionDialog = page.getByRole("dialog", { name: "Aufnahmedatum ändern" });
    await selectionDialog.getByRole("textbox", { name: "Datum", exact: true }).fill("03.05.2026");
    await selectionDialog.getByRole("textbox", { name: "Datum", exact: true }).blur();
    const second = page.waitForResponse((r) => r.url().endsWith("/api/files/bulk-capture-date") && r.request().method() === "POST");
    await selectionDialog.getByRole("button", { name: "Übernehmen" }).click();
    await page.getByRole("alertdialog", { name: "Aufnahmedatum ändern?" }).getByRole("button", { name: "Datum ändern" }).click();
    expect((await (await second).json()).updated_ids).toEqual(ids);
    const dateOnly = await (await request.get(`/api/stored-files/${ids[0]}/metadata`)).json();
    expect(dateOnly.capture_corrected_at).toContain("2026-05-03");
    expect(dateOnly.capture_corrected_has_time).toBe(false);

    // Kopf auf Smartphone-Breite: Aktion bleibt erreichbar
    await page.setViewportSize({ width: 390, height: 844 });
    await page.reload();
    await expect(page.locator(".page-header").getByRole("button", { name: "Datum setzen …" })).toBeVisible();
  } finally {
    await request.post("/api/files/bulk-delete", { data: { file_ids: ids } }).catch(() => {});
  }
});
