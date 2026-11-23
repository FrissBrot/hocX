import { test, expect, type APIRequestContext } from "@playwright/test";
import fs from "node:fs/promises";
import path from "node:path";

import { authFiles } from "./auth";
import { uniquePng } from "./unique-fixture";

// Datei-Import (P0): ZIP hochladen -> Regel «Nicht importieren» per Tastatur anlegen -> Vorschau
// zeigt die ausgeschlossene Datei -> Start -> Bericht. Der job-worker importiert im Hintergrund.
test.use({ storageState: authFiles.admin });

const CRC_TABLE = (() => {
  const table = new Uint32Array(256);
  for (let n = 0; n < 256; n++) {
    let c = n;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    table[n] = c >>> 0;
  }
  return table;
})();

function crc32(buffer: Buffer): number {
  let crc = 0xffffffff;
  for (const byte of buffer) crc = CRC_TABLE[(crc ^ byte) & 0xff] ^ (crc >>> 8);
  return (crc ^ 0xffffffff) >>> 0;
}

/** Minimales ZIP (Methode «stored») mit UTF-8-Namen. */
function storedZip(entries: Record<string, Buffer>): Buffer {
  const locals: Buffer[] = [];
  const centrals: Buffer[] = [];
  let offset = 0;
  for (const [name, data] of Object.entries(entries)) {
    const nameBytes = Buffer.from(name, "utf8");
    const crc = crc32(data);
    const local = Buffer.alloc(30);
    local.writeUInt32LE(0x04034b50, 0);
    local.writeUInt16LE(20, 4);
    local.writeUInt16LE(0x0800, 6);
    local.writeUInt32LE(crc, 14);
    local.writeUInt32LE(data.length, 18);
    local.writeUInt32LE(data.length, 22);
    local.writeUInt16LE(nameBytes.length, 26);
    locals.push(local, nameBytes, data);
    const central = Buffer.alloc(46);
    central.writeUInt32LE(0x02014b50, 0);
    central.writeUInt16LE(20, 4);
    central.writeUInt16LE(20, 6);
    central.writeUInt16LE(0x0800, 8);
    central.writeUInt32LE(crc, 16);
    central.writeUInt32LE(data.length, 20);
    central.writeUInt32LE(data.length, 24);
    central.writeUInt16LE(nameBytes.length, 28);
    central.writeUInt32LE(offset, 42);
    centrals.push(central, nameBytes);
    offset += 30 + nameBytes.length + data.length;
  }
  const centralBuffer = Buffer.concat(centrals);
  const end = Buffer.alloc(22);
  end.writeUInt32LE(0x06054b50, 0);
  end.writeUInt16LE(Object.keys(entries).length, 8);
  end.writeUInt16LE(Object.keys(entries).length, 10);
  end.writeUInt32LE(centralBuffer.length, 12);
  end.writeUInt32LE(offset, 16);
  return Buffer.concat([...locals, centralBuffer, end]);
}

/** Gemeinsamer E2E-Mandant: ein offener Import eines früheren Laufs blockiert den neuen (einer je Verein). */
async function cancelOpenImports(api: APIRequestContext) {
  const jobs = (await (await api.get("/api/cloud-import/jobs")).json()) as { id: string; status: string }[];
  for (const job of jobs.filter((entry) => ["draft", "ready", "queued", "running"].includes(entry.status))) {
    await api.post(`/api/cloud-import/jobs/${job.id}/cancel`);
  }
  await expect
    .poll(async () => ((await (await api.get("/api/cloud-import/jobs")).json()) as { status: string }[]).some((job) => job.status === "cancel_requested"), { timeout: 60_000 })
    .toBe(false);
}

test("ZIP importieren mit Regel, Vorschau und Bericht", async ({ page, request }) => {
  test.setTimeout(240_000);
  await cancelOpenImports(request);
  const stamp = Date.now();
  const photo = uniquePng(await fs.readFile(path.join("e2e/fixtures/photos/sample.png")));
  const skipped = uniquePng(await fs.readFile(path.join("e2e/fixtures/photos/sample.png")));
  const zip = storedZip({ [`Lager ${stamp}/foto.png`]: photo, [`tmp/weg-${stamp}.png`]: skipped });

  await page.goto("/files");
  await page.getByRole("link", { name: "Importieren" }).click();
  await expect(page.getByRole("heading", { name: "Dateien importieren" })).toBeVisible();

  await page.getByRole("radio", { name: /ZIP-Archiv/ }).click();
  await page.getByRole("button", { name: "Weiter", exact: true }).click();
  await page.locator('input[type="file"][accept*="zip"]').setInputFiles({ name: `export-${stamp}.zip`, mimeType: "application/zip", buffer: zip });
  await expect(page.getByText(/2 Dateien gefunden/)).toBeVisible({ timeout: 60_000 });
  await page.getByRole("button", { name: "Weiter zu Regeln und Vorschau" }).click();

  // Regel per Tastatur: Pfad-Muster tippen, Aktion wählen
  await page.getByRole("button", { name: "Regel hinzufügen" }).click();
  const pattern = page.getByLabel("Pfad-Muster");
  await pattern.focus();
  await page.keyboard.type("tmp/**");
  await page.getByLabel("Aktion").selectOption("skip");
  await expect(page.getByText("trifft 1 Datei")).toBeVisible({ timeout: 30_000 });

  await page.getByRole("tab", { name: "Übersprungen" }).click();
  await expect(page.getByRole("cell", { name: `tmp/weg-${stamp}.png` })).toBeVisible();
  await expect(page.getByText("Durch Regel ausgeschlossen").first()).toBeVisible();

  const start = page.getByRole("button", { name: "Import starten" });
  await expect(start).toBeEnabled({ timeout: 30_000 });
  await start.click();
  await page.getByRole("alertdialog").getByRole("button", { name: "Import starten" }).click();

  await expect(page.getByText(/Import abgeschlossen/)).toBeVisible({ timeout: 180_000 });
  await expect(page.getByRole("link", { name: `Lager ${stamp}/foto.png` })).toBeVisible();
  await expect(page.getByText("Der Bericht bleibt erhalten")).toBeVisible();
});
