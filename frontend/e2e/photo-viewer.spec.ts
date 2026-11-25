import { test, expect, type APIRequestContext, type Page } from "@playwright/test";
import fs from "node:fs/promises";
import path from "node:path";
import { authFiles } from "./auth";
import { pngWithGps, uniquePng } from "./unique-fixture";

// Foto-Ansicht (Design «hocX Foto-Ansicht»): öffnen, mit ←/→ blättern, B für Best-of, Vergleich einer
// Duplikat-Gruppe anwenden (Papierkorb) und im Toast rückgängig machen. Die Gruppen berechnet der
// Hintergrundjob; damit der Test nicht auf ihn wartet, liefert die Gruppen-Abfrage hier eine Gruppe
// aus den eben hochgeladenen Fotos - Löschen und Wiederherstellen laufen gegen das echte Backend.
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

test("Foto-Ansicht: blättern, Best-of per Taste, Vergleich anwenden und rückgängig machen", async ({ page, request }) => {
  test.setTimeout(240_000);
  const stem = `ansicht-${Date.now()}`;
  const names = [`${stem}-a.png`, `${stem}-b.png`, `${stem}-c.png`];
  const ids: string[] = [];
  for (const name of names) ids.push(await uploadPhoto(request, name));
  // Best-of gilt je Album: die Fotos in ein eigenes Album legen
  const album = await (await request.post("/api/files/albums", { data: { name: stem } })).json();
  expect((await request.post(`/api/files/albums/${album.id}/items`, { data: { file_ids: ids } })).ok()).toBeTruthy();
  try {
    const listed = await (await request.get(`/api/files?only_images=true&search=${encodeURIComponent(stem)}&limit=10`)).json();
    const images = ids.map((id) => listed.find((item: { id: string }) => item.id === id));
    expect(images.every(Boolean)).toBeTruthy();
    // Duplikat-Gruppe aus a (beste Wahl) und b
    await page.route(/\/api\/files\/similarity-groups\?.*kind=duplicate/, (route) =>
      route.fulfill({ json: { status: "ready", computed_at: new Date().toISOString(), groups: [{ best_id: ids[0], images: images.slice(0, 2) }] } })
    );

    await page.goto("/photos");
    await searchOwnPhotos(page, stem, 3);
    await page.locator(".photo-tile", { has: page.getByRole("checkbox", { name: `${names[0]} auswählen` }) }).locator(".photo-tile-preview").click();

    await expect(page.getByRole("dialog", { name: names[0] })).toBeVisible();
    // Der Name des Dialogs folgt dem aktuellen Foto - beim Blättern über die Klasse suchen.
    const position = page.locator(".photo-viewer .photo-viewer-position");
    const start = await position.textContent();
    const startIndex = Number(start?.split("/")[0].trim());

    // ←/→ blättern (Tastatur) - Richtung je nach Position in der Galerie
    const [forward, back] = startIndex < 3 ? ["ArrowRight", "ArrowLeft"] : ["ArrowLeft", "ArrowRight"];
    await page.keyboard.press(forward);
    await expect(position).toHaveText(`${startIndex < 3 ? startIndex + 1 : startIndex - 1} / 3`);
    await page.keyboard.press(back);
    await expect(position).toHaveText(`${startIndex} / 3`);

    // B: Best-of an und wieder aus
    const best = page.getByRole("dialog").getByRole("button", { name: /Best-of/ }).first();
    const bestBefore = await best.getAttribute("aria-pressed");
    await page.keyboard.press("b");
    await expect(best).toHaveAttribute("aria-pressed", bestBefore === "true" ? "false" : "true");
    await page.keyboard.press("b");
    await expect(best).toHaveAttribute("aria-pressed", bestBefore ?? "false");

    // Zum Foto a, das in der Gruppe steckt: Hinweis auf der Bühne öffnet den Vergleich
    const dialog = page.getByRole("dialog").first();
    await expect(dialog).toHaveAttribute("aria-label", names[0]);
    await dialog.getByRole("button", { name: /1 Duplikat · Vergleichen/ }).click();
    const region = dialog.getByRole("region", { name: "Vergleich" });
    await expect(region).toContainText("1 behalten");
    await expect(region).toContainText("1 in den Papierkorb");
    const removed = page.waitForResponse((r) => r.url().endsWith("/api/files/bulk-delete") && r.request().method() === "POST");
    await region.getByRole("button", { name: "1 in den Papierkorb" }).click();
    expect(await (await removed).json()).toMatchObject({ deleted_ids: [ids[1]] });
    await expect(dialog.getByRole("region", { name: "Vergleich" })).toHaveCount(0);
    await expect(page.getByText("1 Foto in den Papierkorb verschoben")).toBeVisible();

    // Rückgängig im Toast holt b aus dem Papierkorb zurück
    const restored = page.waitForResponse((r) => r.url().endsWith("/api/files/trash/restore") && r.request().method() === "POST");
    await page.getByRole("button", { name: "Rückgängig" }).click();
    expect(await (await restored).json()).toMatchObject({ file_ids: [ids[1]] });
    const trash = await (await request.get("/api/files/trash")).json();
    expect((trash.items as { id: string }[]).some((item) => item.id === ids[1])).toBe(false);

    // Escape schliesst die Ansicht
    await page.keyboard.press("Escape");
    await expect(page.getByRole("dialog")).toHaveCount(0);
  } finally {
    await request.post("/api/files/bulk-delete", { data: { file_ids: ids } }).catch(() => {});
    await request.delete(`/api/files/albums/${album.id}`).catch(() => {});
  }
});

// Kopfzeile der Foto-Ansicht springt beim Blättern nicht (Bug 1.6): Datum mit Uhrzeit, Badges,
// Upload-Hinweis und Ort hängen an den Metadaten, die je Foto nachgeladen werden. Die Höhe der
// Kopfzeile wird in jedem Frame (requestAnimationFrame) und bei jeder Grössenänderung
// (ResizeObserver) erfasst, während schnell geblättert wird und die Metadaten noch laden.
const AT_HUT = { latitude: 46.5101, longitude: 7.7716 };

async function uploadPng(api: APIRequestContext, name: string, gps?: { latitude: number; longitude: number }): Promise<string> {
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

// Nur die eigenen Fotos (eindeutiger Namensstamm) zeigen. Den Suchtext erst nach der Hydrierung
// setzen: ein zu früh getippter Wert im kontrollierten Feld wird beim Hydrieren wieder geleert, dann
// zeigt die Seite auch die Fotos anderer Specs (CI: 7 statt 4). Tippen und Ergebnis darum zusammen
// wiederholen.
async function searchOwnPhotos(page: Page, stem: string, count: number) {
  const search = page.getByPlaceholder(/^Suchen nach Name, Tag/);
  await expect(async () => {
    await search.fill(stem);
    await expect(search).toHaveValue(stem);
    await expect(page.locator(".photo-tile")).toHaveCount(count, { timeout: 10_000 });
    await expect(search).toHaveValue(stem);
  }).toPass({ timeout: 90_000 });
}

type HeaderSample = { t: number; height: number; detail: string };

test("Foto-Ansicht: Kopfzeile behält beim Blättern mit ←/→ ihre Höhe (1440 und 390 px)", async ({ page, request }) => {
  test.setTimeout(300_000);
  const stem = `kopf-${Date.now()}`;
  const names = [`${stem}-a.png`, `${stem}-b.png`, `${stem}-c.png`, `${stem}-d.png`];
  const ids = [
    await uploadPng(request, names[0], AT_HUT),
    await uploadPng(request, names[1]),
    await uploadPng(request, names[2]),
    await uploadPng(request, names[3], AT_HUT),
  ];
  try {
    // a: korrigiertes Datum mit Uhrzeit (Uhrzeit + Badge kommen aus den Metadaten), b: geschätzt,
    // c und d: Uploaddatum (Hinweis-Symbol); a und d mit Ort aus GPS.
    expect((await request.patch(`/api/stored-files/${ids[0]}/capture-correction`, { data: { corrected_date: "2026-09-20", corrected_time: "14:32" } })).ok()).toBeTruthy();
    expect((await request.patch(`/api/stored-files/${ids[1]}/capture-date`, { data: { estimated_taken_on: "2026-09-19" } })).ok()).toBeTruthy();
    for (const id of [ids[0], ids[3]]) {
      await expect
        .poll(async () => (await (await request.get(`/api/stored-files/${id}/metadata`)).json()).place?.name ?? null, { timeout: 30_000 })
        .toBe("Blüemlisalphütte SAC");
    }
    // Metadaten verzögert ausliefern: so liegt zwischen Tastendruck und Antwort sicher ein Fenster,
    // in dem die Kopfzeile noch ohne die Metadaten des neuen Fotos dasteht.
    await page.route(/\/api\/stored-files\/[^/]+\/metadata/, async (route) => {
      await new Promise((resolve) => setTimeout(resolve, 400));
      await route.continue();
    });

    for (const width of [1440, 390]) {
      await page.setViewportSize({ width, height: width > 640 ? 900 : 844 });
      await page.goto("/photos");
      await searchOwnPhotos(page, stem, 4);
      await page.locator(".photo-tile").first().locator(".photo-tile-preview").click();
      const header = page.locator(".photo-viewer .photo-viewer-header");
      const position = page.locator(".photo-viewer .photo-viewer-position");
      await expect(position).toHaveText("1 / 4");
      await page.waitForTimeout(800);

      await header.evaluate((element) => {
        const samples: HeaderSample[] = [];
        const describe = () => {
          const part = (selector: string) => Math.round((element.querySelector(selector) as HTMLElement | null)?.getBoundingClientRect().height ?? -1);
          const subtitle = (element.querySelector(".photo-viewer-subtitle") as HTMLElement | null)?.innerText.replace(/\s+/g, " ") ?? "";
          return `title=${part(".photo-viewer-title-row")} sub=${part(".photo-viewer-subtitle")} actions=${part(".photo-viewer-actions")} «${subtitle}»`;
        };
        const record = () => {
          const height = Math.round(element.getBoundingClientRect().height * 10) / 10;
          const last = samples[samples.length - 1];
          if (!last || last.height !== height) samples.push({ t: Math.round(performance.now()), height, detail: describe() });
        };
        const observer = new ResizeObserver(record);
        observer.observe(element);
        let running = true;
        const loop = () => { record(); if (running) requestAnimationFrame(loop); };
        loop();
        (window as unknown as { __pvHeader: { samples: HeaderSample[]; stop: () => void } }).__pvHeader = {
          samples,
          stop: () => { running = false; observer.disconnect(); },
        };
      });

      // Schnell blättern (kürzer als die Antwortzeit der Metadaten), dann zurück
      for (const key of ["ArrowRight", "ArrowRight", "ArrowRight", "ArrowLeft", "ArrowLeft", "ArrowLeft"]) {
        await page.keyboard.press(key);
        await page.waitForTimeout(150);
      }
      await expect(position).toHaveText("1 / 4");
      // Langsam: jede Antwort abwarten
      for (const key of ["ArrowRight", "ArrowRight", "ArrowRight", "ArrowLeft", "ArrowLeft", "ArrowLeft"]) {
        await page.keyboard.press(key);
        await page.waitForTimeout(700);
      }
      await expect(position).toHaveText("1 / 4");

      const samples = await page.evaluate(() => {
        const recorder = (window as unknown as { __pvHeader: { samples: HeaderSample[]; stop: () => void } }).__pvHeader;
        recorder.stop();
        return recorder.samples;
      });
      const heights = [...new Set(samples.map((sample) => sample.height))];
      await page.screenshot({ path: test.info().outputPath(`viewer-header-${width}.png`) });
      expect(heights, `Kopfzeile bei ${width} px:\n${samples.map((s) => `${s.t} ${s.height} ${s.detail}`).join("\n")}`).toHaveLength(1);
      await page.keyboard.press("Escape");
      await expect(page.getByRole("dialog")).toHaveCount(0);
    }

    // Belegbilder hell/dunkel: Foto mit Ort, korrigierter Uhrzeit und Badge (a)
    for (const width of [1440, 390]) {
      for (const colorScheme of ["light", "dark"] as const) {
        await page.emulateMedia({ colorScheme });
        await page.setViewportSize({ width, height: width > 640 ? 900 : 844 });
        await page.goto("/photos");
        await searchOwnPhotos(page, stem, 4);
        await page.locator(".photo-tile", { has: page.getByRole("checkbox", { name: `${names[0]} auswählen` }) }).locator(".photo-tile-preview").click();
        await expect(page.locator(".photo-viewer .photo-viewer-place")).toBeVisible();
        await expect(page.locator(".photo-viewer .photo-viewer-subtitle")).toContainText("14:32");
        await page.screenshot({ path: test.info().outputPath(`viewer-header-${width}-${colorScheme}.png`) });
        await page.keyboard.press("Escape");
      }
    }
  } finally {
    await request.post("/api/files/bulk-delete", { data: { file_ids: ids } }).catch(() => {});
  }
});
