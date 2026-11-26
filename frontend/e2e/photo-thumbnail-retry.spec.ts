import { test, expect, type APIRequestContext } from "@playwright/test";
import fs from "node:fs/promises";
import path from "node:path";
import { authFiles } from "./auth";
import { uniquePng } from "./unique-fixture";

// Bug 1.6: Beim Scrollen der Fotogalerie zeigten einzelne Kacheln dauerhaft «Vorschau nicht
// verfügbar», obwohl die Vorschau existierte. Ursache: ein einziger fehlgeschlagener Thumbnail-
// Request (503 thumbnail_busy/db_busy unter Last, 429) setzte die Kachel auf den Platzhalter, bis
// die virtualisierte Zeitleiste sie neu montierte. Hier beantwortet der Test den ersten Request je
// Vorschau mit 503 bzw. 429 - die Kachel muss das Bild danach ohne Scrollen selbst nachladen.
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

test("Fotogalerie: Vorschau lädt nach einem 503/429 automatisch nach, ohne Scrollen", async ({ page, request }) => {
  test.setTimeout(240_000);
  const stem = `thumbretry-${Date.now()}`;
  const names = [`${stem}-a.png`, `${stem}-b.png`];
  const ids: string[] = [];
  for (const name of names) ids.push(await uploadPhoto(request, name));
  try {
    // Erster Request je Foto schlägt fehl (a: 503 wie thumbnail_busy, b: 429), alle weiteren gehen durch.
    const failedOnce = new Set<string>();
    const thumbnailRequests: string[] = [];
    await page.route(/\/api\/stored-files\/[0-9a-f-]+\/thumbnail/, async (route) => {
      const id = /stored-files\/([0-9a-f-]+)\/thumbnail/.exec(route.request().url())?.[1] ?? "";
      if (!ids.includes(id)) return route.continue();
      thumbnailRequests.push(id);
      if (!failedOnce.has(id)) {
        failedOnce.add(id);
        const status = id === ids[0] ? 503 : 429;
        return route.fulfill({ status, headers: { "Retry-After": "1", "Cache-Control": "no-store" }, json: { detail: "busy" } });
      }
      return route.continue();
    });

    await page.goto("/photos");
    const search = page.getByPlaceholder(/^Suchen nach Name, Tag/);
    await expect(async () => {
      await search.fill(stem);
      await expect(search).toHaveValue(stem);
      await expect(page.locator(".photo-tile")).toHaveCount(2, { timeout: 10_000 });
    }).toPass({ timeout: 90_000 });

    // Ohne Scrollen: beide Kacheln zeigen am Ende das Bild, nie den Platzhalter.
    const tiles = page.locator(".photo-tile");
    await expect(tiles.locator(".photo-tile-preview-loaded")).toHaveCount(2, { timeout: 30_000 });
    await expect(tiles.getByText("Vorschau nicht verfügbar")).toHaveCount(0);
    for (const id of ids) {
      // Genau ein Fehlschlag, danach eine (begrenzte) Wiederholung - kein Request-Sturm.
      const count = thumbnailRequests.filter((value) => value === id).length;
      expect(count).toBeGreaterThanOrEqual(2);
      expect(count).toBeLessThanOrEqual(3);
    }
  } finally {
    await request.post("/api/files/bulk-delete", { data: { file_ids: ids } }).catch(() => {});
  }
});
