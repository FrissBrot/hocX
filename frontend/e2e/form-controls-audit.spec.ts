import { test, expect } from "@playwright/test";
import fs from "node:fs/promises";

// Audit: jedes sichtbare Formular-Steuerelement der Hauptseiten muss die hocX-Optik haben, nicht
// die des Browsers. Erkennungsmerkmale der Chrome-Standardoptik: Rahmen «inset» (Eingabefelder)
// bzw. «outset» (Buttons), Standard-Innenabstand von Textfeldern, Dropdowns mit System-Pfeil
// (appearance ≠ none), Checkboxen/Radios ohne accent-color. Der Bericht liegt unter
// test-results/form-controls-audit.json. Dialoge werden nicht geöffnet: dort gelten dieselben
// zentralen Regeln.

const ROUTES = [
  "/", "/agenda", "/connections", "/cycles", "/documents", "/documents/assets", "/documents/brand",
  "/documents/exports", "/elements", "/events", "/files", "/finances", "/fines",
  "/lists", "/participants", "/photos", "/protocols", "/settings", "/shared-links", "/statistics",
  "/submission-assignments", "/task-packages", "/templates", "/tenant-settings", "/tenant-settings/abo",
  "/tenant-settings/activity", "/tenant-settings/domains", "/tenant-settings/privacy",
  "/tenant-settings/retention", "/tenant-settings/verification", "/todos", "/tools", "/tools/import",
  "/tools/word-import", "/users", "/users/roles", "/website",
];

type Finding = { route: string; theme: string; control: string; reason: string };

test("Formular-Steuerelemente haben überall die hocX-Optik", async ({ page }) => {
  test.setTimeout(900_000);
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.addInitScript(() => {
    (window as unknown as { __auditControls: () => { control: string; reason: string }[] }).__auditControls = () => {
          const result: { control: string; reason: string }[] = [];
          const describe = (element: Element) => {
            const tag = element.tagName.toLowerCase();
            const type = element.getAttribute("type");
            const label = element.getAttribute("aria-label") || element.getAttribute("name") || element.getAttribute("placeholder") || (element.textContent || "").trim().slice(0, 30);
            const classes = (element.getAttribute("class") || "").trim().split(/\s+/).filter(Boolean).slice(0, 2).join(".");
            return `${tag}${type ? `[type=${type}]` : ""}${classes ? `.${classes}` : ""}${label ? ` «${label}»` : ""}`;
          };
          const visible = (element: Element) => {
            const rect = element.getBoundingClientRect();
            const style = getComputedStyle(element);
            return rect.width > 0 && rect.height > 0 && style.visibility !== "hidden" && style.opacity !== "0";
          };
          for (const element of Array.from(document.querySelectorAll("input, select, textarea, button"))) {
            if (!visible(element)) continue;
            const style = getComputedStyle(element);
            const tag = element.tagName.toLowerCase();
            const type = (element.getAttribute("type") || "text").toLowerCase();
            if (tag === "select") {
              const select = element as HTMLSelectElement;
              if (!select.multiple && select.size <= 1 && style.appearance !== "none") result.push({ control: describe(element), reason: "System-Dropdown" });
              continue;
            }
            if (tag === "input" && (type === "checkbox" || type === "radio")) {
              if (style.accentColor === "auto") result.push({ control: describe(element), reason: "Checkbox/Radio ohne accent-color" });
              continue;
            }
            if (tag === "input" && ["hidden", "range", "color", "image"].includes(type)) continue;
            if (tag === "input" && type === "file") {
              result.push({ control: describe(element), reason: "Sichtbares Datei-Feld" });
              continue;
            }
            if (tag === "button" || (tag === "input" && ["button", "submit", "reset"].includes(type))) {
              if (style.borderTopStyle === "outset") result.push({ control: describe(element), reason: "Browser-Button" });
              continue;
            }
            if (style.borderTopStyle === "inset" || style.borderTopStyle === "outset") {
              result.push({ control: describe(element), reason: "Browser-Rahmen" });
            } else if (tag === "textarea" && style.paddingTop === "2px" && style.borderTopLeftRadius === "0px") {
              result.push({ control: describe(element), reason: "Browser-Textbereich" });
            } else if (tag === "input" && style.paddingTop === "1px" && style.borderTopLeftRadius === "0px") {
              result.push({ control: describe(element), reason: "Browser-Eingabefeld" });
            }
          }
          return result;
        };
  });
  // Selbstprüfung: rohe Browser-Steuerelemente ausserhalb jeder hocX-Klasse muss der Audit melden
  await page.goto("/");
  const probe = await page.evaluate(() => {
    const host = document.createElement("div");
    host.innerHTML = '<input aria-label="probe-text"><textarea aria-label="probe-area"></textarea><select aria-label="probe-select" style="all: revert"><option>a</option></select><input type="checkbox" aria-label="probe-check" style="accent-color: auto">';
    host.setAttribute("style", "all: initial; position: fixed; top: 0; left: 0; z-index: 99999; background: white");
    document.body.appendChild(host);
    const result = (window as unknown as { __auditControls: () => { control: string; reason: string }[] }).__auditControls().filter((item) => item.control.includes("probe"));
    host.remove();
    return result;
  });
  console.log("Selbstprüfung:", JSON.stringify(probe));
  // Auf Browser-Standard zurückgesetzte Felder (all: revert / accent-color: auto) erkennt er sicher;
  // rohe Text- und Textbereichsfelder ohne Klasse haben dagegen die zentrale Grundoptik
  expect(probe.map((item) => item.reason).sort()).toEqual(["Checkbox/Radio ohne accent-color", "System-Dropdown"]);
  const findings: Finding[] = [];
  for (const theme of ["light", "dark"]) {
    for (const route of ROUTES) {
      // `next dev` kompiliert Routen beim ersten Aufruf und antwortet dabei gelegentlich leer
      await expect(async () => {
        await page.goto(route, { timeout: 60_000 });
        await page.evaluate((value) => localStorage.setItem("hocx-theme", value), theme);
        await page.reload({ timeout: 60_000 });
      }).toPass({ timeout: 180_000 });
      await page.waitForLoadState("networkidle").catch(() => undefined);
      const found = await page.evaluate(() => (window as unknown as { __auditControls: () => { control: string; reason: string }[] }).__auditControls());
      findings.push(...found.map((item) => ({ ...item, route, theme })));
    }
  }
  await fs.mkdir("test-results", { recursive: true });
  await fs.writeFile("test-results/form-controls-audit.json", JSON.stringify(findings, null, 2));
  expect(findings).toEqual([]);
});
