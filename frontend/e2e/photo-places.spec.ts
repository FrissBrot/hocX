import { test, expect, type APIRequestContext } from "@playwright/test";
import fs from "node:fs/promises";
import path from "node:path";
import { authFiles } from "./auth";
import { pngWithGps, uniquePng } from "./unique-fixture";

// Foto-Standorte (Migration 0260): Ortsname aus GPS, Ortssuche (Treffertyp «Ort») mit Umkreis und
// Ort von Hand mit Rückgängig. Ortsdaten: kleiner Testdatensatz, den scripts/e2e.sh beim Start lädt
// (backend/tests/fixtures/geo_places) - kein Download.
test.use({ storageState: authFiles.admin });

const AT_HUT = { latitude: 46.5101, longitude: 7.7716 };

async function uploadPhoto(api: APIRequestContext, name: string, gps?: { latitude: number; longitude: number }): Promise<string> {
  let buffer = uniquePng(await fs.readFile(path.join("e2e/fixtures/photos/sample.png")));
  if (gps) buffer = pngWithGps(buffer, gps.latitude, gps.longitude);
  const response = await api.post("/api/files/gallery-uploads", { multipart: { files: { name, mimeType: "image/png", buffer } } });
  expect(response.ok(), await response.text()).toBeTruthy();
  const job = await response.json();
  await expect
    .poll(async () => (await (await api.get(`/api/files/gallery-upload-jobs/${job.id}`)).json()).status, { timeout: 60_000 })
    .toBe("done");
  const detail = await (await api.get(`/api/files/gallery-upload-jobs/${job.id}`)).json();
  return detail.imported_items[0].id as string;
}

async function deletePhoto(api: APIRequestContext, fileId: string) {
  await api.post("/api/files/bulk-delete", { data: { file_ids: [fileId] } });
}

test("Ortsname aus GPS, Ortssuche mit Umkreis und Umgebungssuche aus der Foto-Ansicht", async ({ page, request }) => {
  test.setTimeout(180_000);
  const name = `ort-gps-${Date.now()}.png`;
  const fileId = await uploadPhoto(request, name, AT_HUT);
  try {
    await expect
      .poll(async () => (await (await request.get(`/api/stored-files/${fileId}/metadata`)).json()).place?.name ?? null, { timeout: 30_000 })
      .toBe("Blüemlisalphütte SAC");

    await page.goto("/photos");
    await page.getByPlaceholder(/^Suchen nach Name, Tag/).fill("Blüemlisalp");
    const suggestion = page.getByRole("button", { name: "Blüemlisalphütte SAC · Hütte · Kandersteg BE" });
    await expect(suggestion).toBeVisible();
    // Tastatur: Orts-Treffer fokussieren und mit Enter wählen
    await suggestion.focus();
    await page.keyboard.press("Enter");
    await expect(page.getByText("Umgebung Blüemlisalphütte SAC · 2 km")).toBeVisible();
    await expect(page.getByPlaceholder(/^Suchen nach Name, Tag/)).toHaveValue("");
    await page.screenshot({ path: test.info().outputPath("places-umkreis.png") });
    const select = page.getByRole("checkbox", { name: `${name} auswählen` });
    await expect(select).toBeVisible();

    await page.getByRole("button", { name: "Umkreis um 10 km erweitern" }).click();
    await expect(page.getByText("Umgebung Blüemlisalphütte SAC · 12 km")).toBeVisible();

    // Foto-Ansicht: Ort unter dem Dateinamen, Klick startet die Umgebungssuche
    await page.locator(".photo-tile", { has: select }).locator(".photo-tile-preview").click();
    const viewer = page.getByRole("dialog", { name });
    const placeLink = viewer.getByRole("button", { name: "Nähe Blüemlisalphütte SAC, Kandersteg BE" });
    await expect(placeLink).toBeVisible();
    await expect(viewer.getByText("aus GPS")).toBeVisible();
    await page.screenshot({ path: test.info().outputPath("places-viewer.png") });
    await placeLink.click();
    await expect(viewer).toHaveCount(0);
    await expect(page.getByText("Umgebung Blüemlisalphütte SAC · 2 km")).toBeVisible();
    await expect(page.getByRole("checkbox", { name: `${name} auswählen` })).toBeVisible();
  } finally {
    await deletePhoto(request, fileId);
  }
});

test("Ort von Hand setzen (Mehrfachauswahl) und rückgängig machen", async ({ page, request }) => {
  test.setTimeout(180_000);
  const name = `ort-hand-${Date.now()}.png`;
  const fileId = await uploadPhoto(request, name);
  try {
    await page.goto("/photos");
    await page.getByPlaceholder(/^Suchen nach Name, Tag/).fill(name);
    await page.getByRole("checkbox", { name: `${name} auswählen` }).click();
    await page.locator(".photo-bulk-bar").getByRole("button", { name: "Ort", exact: true }).click();

    const dialog = page.getByRole("dialog", { name: "Ort setzen" });
    await dialog.getByText("Ort wählen").click();
    await page.getByRole("combobox").fill("Kanderst");
    await page.getByRole("option", { name: "Kandersteg · Dorf · BE" }).click();
    await page.screenshot({ path: test.info().outputPath("places-dialog.png") });
    const saved = page.waitForResponse((r) => r.url().endsWith("/api/photo-places/assign") && r.request().method() === "POST");
    await dialog.getByRole("button", { name: "Ort setzen" }).click();
    const response = await saved;
    expect(response.ok(), await response.text()).toBeTruthy();
    expect((await response.json()).updated_ids).toEqual([fileId]);
    await expect(page.getByText("Ort für 1 Foto gesetzt")).toBeVisible();

    const metadata = await (await request.get(`/api/stored-files/${fileId}/metadata`)).json();
    expect(metadata.place.locality_name).toBe("Kandersteg");
    expect(metadata.place.source).toBe("manual");

    const undone = page.waitForResponse((r) => /\/api\/place-changes\/[^/]+\/undo$/.test(r.url()));
    await page.getByRole("button", { name: "Rückgängig" }).click();
    expect((await undone).ok()).toBeTruthy();
    await expect(page.getByText("Ort von 1 Foto wiederhergestellt")).toBeVisible();
    const after = await (await request.get(`/api/stored-files/${fileId}/metadata`)).json();
    expect(after.place ?? null).toBeNull();
  } finally {
    await deletePhoto(request, fileId);
  }
});
