import { test, expect, type APIRequestContext } from "@playwright/test";
import fs from "node:fs/promises";
import path from "node:path";
import { authFiles } from "./auth";
import { uniquePng } from "./unique-fixture";

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
    await page.getByPlaceholder(/^Suchen nach Name, Tag/).fill(stem);
    await expect(page.locator(".photo-tile")).toHaveCount(3);
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
