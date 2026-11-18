import { test, expect, type APIRequestContext, type Page } from "@playwright/test";
import fs from "node:fs/promises";
import path from "node:path";
import { uniquePng } from "./unique-fixture";

// Button-Regeln aus design/DESIGN.md (Abschnitt 7), im echten Browser geprüft statt nur im CSS:
// 1. Text-Buttons nebeneinander (gleicher Container) sind gleich hoch (Token --button-height).
// 2. Eine Nebenaktion (button-secondary) trägt nie die dunkle Primärfarbe - das war der
//    wiederkehrende «dunkle Button im hellen Design».
// Läuft in Hell und Dunkel, Desktop und Smartphone. Der Design-Checker
// (scripts/check-design-rules.py, Regeln button-hoehe/button-hintergrund) fängt das Gleiche
// schon im CSS ab; dieser Test sichert Fälle, die nur zur Laufzeit sichtbar werden.

const PAGES = ["/", "/files", "/photos", "/events", "/protocols", "/lists", "/todos", "/participants", "/users", "/fines", "/finances", "/templates", "/tenant-settings"];
const VARIANTS = ".button-primary, .button-secondary, .button-danger, .button-ghost";
const EXCLUDED = ".button-icon, .button-icon-soft, .button-icon-soft-sm, .button-pill";

type Finding = { page: string; theme: string; width: number; problem: string };

async function audit(page: Page): Promise<string[]> {
  return page.evaluate(
    ({ variants, excluded }) => {
      const problems: string[] = [];
      const probe = document.createElement("div");
      probe.style.background = "var(--primary)";
      document.body.appendChild(probe);
      const primary = getComputedStyle(probe).backgroundColor;
      probe.remove();
      const visible = (element: Element) => {
        const box = (element as HTMLElement).getBoundingClientRect();
        return box.width > 0 && box.height > 0 && getComputedStyle(element).visibility !== "hidden";
      };
      const label = (element: Element) => (element.textContent || element.getAttribute("aria-label") || element.className).toString().trim().slice(0, 40);
      const buttons = Array.from(document.querySelectorAll(variants)).filter((element) => !element.matches(excluded) && visible(element));
      const byParent = new Map<Element, Element[]>();
      for (const button of buttons) {
        const parent = button.parentElement;
        if (!parent || parent.closest("[data-button-sizes='mixed']")) continue;
        byParent.set(parent, [...(byParent.get(parent) ?? []), button]);
        if (button.matches(".button-secondary") && getComputedStyle(button).backgroundColor === primary) {
          problems.push(`Nebenaktion «${label(button)}» hat die Primärfarbe`);
        }
      }
      for (const group of byParent.values()) {
        if (group.length < 2) continue;
        const heights = group.map((button) => Math.round((button as HTMLElement).getBoundingClientRect().height));
        if (Math.max(...heights) - Math.min(...heights) > 1) {
          problems.push(`Ungleich hohe Buttons: ${group.map((button, index) => `«${label(button)}» ${heights[index]}px`).join(", ")}`);
        }
      }
      return problems;
    },
    { variants: VARIANTS, excluded: EXCLUDED }
  );
}

test("Buttons sind nebeneinander gleich hoch und Nebenaktionen nie dunkel", async ({ page }) => {
  test.setTimeout(420_000);
  const findings: Finding[] = [];
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 900 });
    for (const theme of ["light", "dark"]) {
      for (const path of PAGES) {
        await page.goto(path, { timeout: 60_000 });
        await page.evaluate((value) => localStorage.setItem("hocx-theme", value), theme);
        await page.reload({ timeout: 60_000 });
        await page.waitForLoadState("networkidle").catch(() => undefined);
        for (const problem of await audit(page)) findings.push({ page: path, theme, width, problem });
      }
    }
  }
  expect(findings, JSON.stringify(findings, null, 2)).toEqual([]);
});

// Öffentliche Teilen-Seite /share/<token> (Design «hocX Public Teilen»): ohne Anmeldung, eigener
// Kopf mit «Auswählen» (Nebenaktion) und «Alle herunterladen (ZIP)» - hier war «Auswählen» im
// Dunkelmodus einmal dunkel und die Buttons ungleich hoch. Geprüft im Normal- und im
// Auswahlmodus, für einen Dateien-Link (Kacheln und Liste) und einen Foto-Link.

/** Minimales, gültiges PDF mit eigenem Inhalt je Lauf (exakte Duplikate werden übersprungen). */
function uniquePdf(label: string): Buffer {
  const text = `${label} ${Date.now()}`; // i18n-ok: Testinhalt, kein UI-Text
  const stream = `BT /F1 24 Tf 72 720 Td (${text}) Tj ET`;
  const objects = [
    "<< /Type /Catalog /Pages 2 0 R >>",
    "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
    "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
    `<< /Length ${stream.length} >>\nstream\n${stream}\nendstream`,
    "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
  ];
  let body = "%PDF-1.4\n";
  const offsets: number[] = [];
  objects.forEach((object, index) => {
    offsets.push(body.length);
    body += `${index + 1} 0 obj\n${object}\nendobj\n`;
  });
  const xref = body.length;
  body += `xref\n0 ${objects.length + 1}\n0000000000 65535 f \n`;
  for (const offset of offsets) body += `${String(offset).padStart(10, "0")} 00000 n \n`;
  body += `trailer\n<< /Size ${objects.length + 1} /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF\n`;
  return Buffer.from(body, "latin1");
}

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

async function createShareLink(api: APIRequestContext, name: string, fileIds: string[]): Promise<string> {
  const response = await api.post("/api/share-links", { data: { name, file_ids: fileIds } });
  expect(response.ok(), await response.text()).toBeTruthy();
  return (await response.json()).url as string;
}

test("Öffentliche Teilen-Seite: Buttons gleich hoch, «Auswählen» nie dunkel", async ({ request, browser }, testInfo) => {
  test.setTimeout(300_000);
  const documents = await request.post("/api/files/document-uploads", {
    multipart: {
      files: { name: "Jahresbericht.pdf", mimeType: "application/pdf", buffer: uniquePdf("Jahresbericht") },
    },
  });
  expect(documents.ok(), await documents.text()).toBeTruthy();
  const pdfId = (await documents.json()).items[0].id as string;
  const photoIds = [await uploadPhoto(request, "lager-1.png"), await uploadPhoto(request, "lager-2.png")];
  const filesUrl = await createShareLink(request, "Unterlagen Generalversammlung", [pdfId, photoIds[0]]);
  const photosUrl = await createShareLink(request, "Sommerlager", photoIds);
  // Die Seitenvorschau erzeugt die Dokument-Pipeline im Hintergrund - kurz darauf warten, ohne
  // den Test davon abhängig zu machen (ohne Vorschau zeigt die Kachel das Dateisymbol).
  const token = filesUrl.split("/").pop();
  await expect
    .poll(async () => {
      const share = await (await request.get(`/api/public/share/${token}`)).json();
      return Boolean(share.files.find((file: { id: string }) => file.id === pdfId)?.thumbnail_url);
    }, { timeout: 30_000 })
    .toBe(true)
    .catch(() => undefined);

  const context = await browser.newContext({ storageState: { cookies: [], origins: [] } });
  const page = await context.newPage();
  const findings: Finding[] = [];
  const shot = async (label: string) => page.screenshot({ path: testInfo.outputPath(`${label}.png`), fullPage: true });
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 900 });
    for (const theme of ["light", "dark"]) {
      for (const [kind, url] of [["dateien", filesUrl], ["fotos", photosUrl]] as const) {
        await page.goto(url, { timeout: 60_000 });
        await page.evaluate((value) => localStorage.setItem("hocx-theme", value), theme);
        await page.reload({ timeout: 60_000 });
        await page.waitForLoadState("networkidle").catch(() => undefined);
        await expect(page.getByRole("button", { name: /Auswählen|Select/ })).toBeVisible();
        for (const problem of await audit(page)) findings.push({ page: `${kind}`, theme, width, problem });
        await shot(`share-${kind}-${theme}-${width}`);

        await page.getByRole("button", { name: /Auswählen|Select/ }).click();
        await page.locator(".public-share-grid button, .public-share-masonry button").first().click();
        for (const problem of await audit(page)) findings.push({ page: `${kind} (Auswahl)`, theme, width, problem });
        await shot(`share-${kind}-${theme}-${width}-auswahl`);

        if (kind === "dateien") {
          await page.getByRole("button", { name: /Abbrechen|Cancel/ }).click();
          await page.getByRole("button", { name: /^(Liste|List)$/ }).click();
          await shot(`share-${kind}-${theme}-${width}-liste`);
          await page.locator(".public-share-row-open").first().click();
        } else {
          await page.getByRole("button", { name: /Abbrechen|Cancel/ }).click();
          await page.locator(".public-share-masonry button").first().click();
        }
        await expect(page.getByRole("dialog")).toBeVisible();
        await shot(`share-${kind}-${theme}-${width}-viewer`);
        await page.keyboard.press("Escape");
        await expect(page.getByRole("dialog")).toHaveCount(0);
      }
    }
  }
  await context.close();
  expect(findings, JSON.stringify(findings, null, 2)).toEqual([]);
});
