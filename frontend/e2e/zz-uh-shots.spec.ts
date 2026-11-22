import { test, expect } from "@playwright/test";
import fs from "node:fs/promises";
import path from "node:path";
import { authFiles } from "./auth";
import { uniquePng } from "./unique-fixture";

// Nur für die Sichtprüfung (nicht committet): Upload-Verlauf hell/dunkel bei 1440 und 390 px.
test.use({ storageState: authFiles.admin });
const dir = "test-results/uh-shots";

test("Screenshots Upload-Verlauf", async ({ browser, request }) => {
  test.setTimeout(300_000);
  await fs.mkdir(dir, { recursive: true });
  const job = await (await request.post("/api/upload-jobs", { data: { channel: "gallery", tags: ["Sommerlager"] } })).json();
  for (let index = 0; index < 4; index += 1) {
    const buffer = uniquePng(await fs.readFile(path.join("e2e/fixtures/photos/sample.png")));
    const response = await request.post("/api/files/gallery-uploads", {
      multipart: { files: { name: `lager-${index + 1}.png`, mimeType: "image/png", buffer }, upload_job_id: job.id, tags: "Sommerlager" },
    });
    expect(response.ok(), await response.text()).toBeTruthy();
  }
  await request.post(`/api/upload-jobs/${job.id}/client-results`, { data: { items: [{ name: "video-gross.mov", size: 900000000, code: "too_large" }] } });
  await request.post(`/api/upload-jobs/${job.id}/complete`);
  await expect.poll(async () => (await (await request.get(`/api/upload-jobs/${job.id}`)).json()).status, { timeout: 90_000 }).toMatch(/done|partial/);
  const ids = (await (await request.get(`/api/upload-jobs/${job.id}/file-ids?only_images=true`)).json()).file_ids;
  await request.post("/api/files/bulk-capture-date", { data: { file_ids: ids, mode: "set", corrected_date: "2026-07-12", corrected_time: "14:30" } });
  await request.post("/api/files/bulk-capture-date", { data: { file_ids: ids, mode: "shift", shift_hours: -1, shift_minutes: -15, upload_job_id: job.id } });

  for (const scheme of ["light", "dark"] as const) {
    for (const width of [1440, 390]) {
      const context = await browser.newContext({ storageState: authFiles.admin, colorScheme: scheme, viewport: { width, height: width > 600 ? 900 : 844 } });
      const page = await context.newPage();
      const snap = async (name: string) => {
        await page.waitForLoadState("networkidle").catch(() => undefined);
        await page.waitForTimeout(400);
        await page.screenshot({ path: `${dir}/${name}-${scheme}-${width}.png`, fullPage: true });
      };
      await page.goto("/photos/uploads");
      await snap("verlauf");
      await page.goto(`/photos/uploads/${job.id}`);
      await snap("vorgang-fotos");
      await page.getByRole("tab", { name: /Ergebnisliste/ }).click();
      await snap("vorgang-ergebnisliste");
      await page.getByRole("tab", { name: "Datumskorrekturen" }).click();
      await snap("vorgang-korrekturen");
      await page.getByRole("tab", { name: "Fotos" }).click();
      await page.getByRole("checkbox", { name: "lager-1.png auswählen" }).click();
      await page.locator(".photo-bulk-bar").getByRole("button", { name: "Alle dieses Uploads auswählen" }).click();
      await snap("vorgang-auswahl");
      await page.locator(".photo-bulk-bar").getByRole("button", { name: "Aufnahmedatum" }).click();
      const dialog = page.getByRole("dialog", { name: "Aufnahmedatum ändern" });
      await dialog.getByRole("tab", { name: "Verschieben" }).click();
      await dialog.getByRole("tab", { name: "Früher" }).click();
      await dialog.getByLabel("Stunden").fill("1");
      await dialog.getByLabel("Minuten").fill("15");
      await dialog.getByRole("button", { name: "Vorschau" }).click();
      await expect(dialog.getByText(/Bilder werden geändert/)).toBeVisible();
      await page.screenshot({ path: `${dir}/dialog-verschieben-${scheme}-${width}.png` });
      await context.close();
    }
  }
});
