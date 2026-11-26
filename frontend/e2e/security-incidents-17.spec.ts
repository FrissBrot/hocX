import { mkdirSync } from "node:fs";
import { randomBytes } from "node:crypto";
import AxeBuilder from "@axe-core/playwright";
import { test, expect, request, type APIRequestContext, type Page } from "@playwright/test";
import { authFiles, platformAdminSpecPasskeyFile } from "./auth";
import { SoftPasskey, stepUpHeaders } from "./soft-passkey";

// Sicherheitsbereich 1.7: Vorfälle (Bündelung, Übernehmen, Status, Notiz mit Passkey) und Lagebild.
//
// Eigener Passkey dieser Spec (auth.ts, platformAdminSpecPasskeys): ein geteilter Signaturzähler über
// parallele Worker sperrt den Passkey als möglichen Klon. Die Oberfläche läuft echt (step-up/start,
// navigator.credentials); die Route ersetzt nur den Header der eigentlichen Anfrage durch eine echte,
// an Methode, Pfad und Body gebundene Bestätigung des Software-Passkeys (wie security-admin-16).
const passkeyFile = platformAdminSpecPasskeyFile("security-incidents");
const baseURL = process.env.PLAYWRIGHT_BASE_URL ?? "http://127.0.0.1:13000";
const origin = new URL(baseURL).origin;
// Screenshots hell/dunkel bei 1440 und 390 px (test-results ist nicht eingecheckt)
const SHOTS = "test-results/secadm-17";

type IncidentRow = { id: number; rule: string; status: string; key: string };

async function confirmStepUps(page: Page): Promise<{ api: APIRequestContext; passkey: SoftPasskey }> {
  const passkey = await SoftPasskey.load(passkeyFile);
  expect(passkey, "Software-Passkey aus auth.setup.ts fehlt").toBeTruthy();
  const api = await request.newContext({ baseURL, storageState: authFiles.platformAdmin, extraHTTPHeaders: { Origin: origin } });
  await page.addInitScript(() => {
    const one = new Uint8Array([1]).buffer;
    Object.defineProperty(navigator.credentials, "get", {
      configurable: true,
      value: async () => ({ id: "AQ", rawId: one, type: "public-key", response: { clientDataJSON: one, authenticatorData: one, signature: one, userHandle: null } }),
    });
  });
  await page.route("**/api/admin/mfa/step-up/start", (route) => route.fulfill({ json: { flow_token: "e2e", public_key: { challenge: "AQ", rpId: "localhost" } } }));
  await page.route(/\/api\/admin\/auth-security\/incidents\/\d+\/(assign|status|notes|block)$/, async (route) => {
    const original = route.request();
    const url = new URL(original.url());
    const purpose = url.pathname.endsWith("/block") ? "security-block" : "security-incident";
    const confirm = await stepUpHeaders(api, passkey!, origin, purpose, original.method(), url.pathname, original.postData() ?? "");
    const headers = Object.fromEntries(Object.entries(original.headers()).filter(([name]) => name.toLowerCase() !== "x-hocx-step-up"));
    await route.continue({ headers: { ...headers, ...confirm } });
  });
  return { api, passkey: passkey! };
}

/** Password Spraying aus dem Netz des Testrunners: Fehlversuche auf verschiedene, unbekannte Adressen. */
async function spray(count: number) {
  const anonymous = await request.newContext({ baseURL, extraHTTPHeaders: { Origin: origin } });
  for (let index = 0; index < count; index += 1) {
    await anonymous.post("/api/auth/login", { data: { email: `spray-${randomBytes(5).toString("hex")}@example.invalid`, password: "falsch-falsch" } });
  }
  await anonymous.dispose();
}

async function waitForIncident(api: APIRequestContext, rule: string): Promise<IncidentRow> {
  let found: IncidentRow | undefined;
  // Der Systemmonitor läuft alle 30 s und bündelt die Regel zu einem Vorfall
  await expect
    .poll(async () => {
      const body = (await (await api.get("/api/admin/auth-security/incidents?status=open&limit=100")).json()) as { items: IncidentRow[] };
      found = body.items.find((item) => item.rule === rule);
      return Boolean(found);
    }, { timeout: 150_000, intervals: [5_000] })
    .toBe(true);
  return found!;
}

async function noOverflowOrOverlap(page: Page) {
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(391);
  const overlaps = await page.evaluate(() => {
    const found: string[] = [];
    for (const list of Array.from(document.querySelectorAll('[role="tablist"]'))) {
      const boxes = Array.from(list.querySelectorAll('[role="tab"]')).map((tab) => {
        const range = document.createRange();
        range.selectNodeContents(tab);
        return { label: (tab.textContent ?? "").trim(), rect: range.getBoundingClientRect() };
      }).filter((item) => item.rect.width > 0 && item.rect.height > 0);
      for (let i = 0; i < boxes.length; i += 1) {
        for (let j = i + 1; j < boxes.length; j += 1) {
          const a = boxes[i].rect;
          const b = boxes[j].rect;
          if (a.left < b.right - 1 && b.left < a.right - 1 && a.top < b.bottom - 1 && b.top < a.bottom - 1) found.push(`${boxes[i].label} / ${boxes[j].label}`);
        }
      }
    }
    return found;
  });
  expect(overlaps).toEqual([]);
}

async function axe(page: Page) {
  const result = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).disableRules(["scrollable-region-focusable"]).analyze();
  expect(result.violations.map((violation) => `${violation.id}: ${violation.nodes.slice(0, 3).map((node) => node.target.join(" ")).join(" | ")}`)).toEqual([]);
}

test.describe("Sicherheitsbereich 1.7: Vorfälle und Lagebild", () => {
  test.use({ storageState: authFiles.platformAdmin });
  test.describe.configure({ mode: "serial" });
  test.setTimeout(360_000);

  test("Spraying wird zu einem Vorfall; Übernehmen, Fehlalarm mit Begründung und Notiz per Tastatur und Passkey", async ({ page }) => {
    const { api, passkey } = await confirmStepUps(page);
    try {
      await spray(12);
      const incident = await waitForIncident(api, "spraying");
      const label = `INC-${String(incident.id).padStart(4, "0")}`;
      // derselbe Schlüssel bündelt: weitere Fehlversuche ergeben keinen zweiten offenen Vorfall
      await spray(2);
      await page.waitForTimeout(35_000);
      const open = (await (await api.get("/api/admin/auth-security/incidents?status=open&limit=100")).json()) as { items: IncidentRow[] };
      expect(open.items.filter((item) => item.key === incident.key)).toHaveLength(1);

      await page.goto("/admin/security/incidents");
      await expect(page.getByRole("heading", { name: "Vorfälle", level: 1 })).toBeVisible();
      const row = page.getByRole("button", { name: `${label} öffnen` });
      await row.focus();
      await page.keyboard.press("Enter");
      await expect(page).toHaveURL(new RegExp(`incident=${incident.id}`));
      const drawer = page.getByRole("complementary", { name: "Password Spraying aus einem Netz" });
      await expect(drawer.getByRole("heading", { name: "Zeitleiste" })).toBeVisible();
      await expect(drawer.getByText("Regel ausgelöst")).toBeVisible();

      await drawer.getByRole("button", { name: "Übernehmen" }).click();
      await expect(page.getByText("Du bist jetzt zuständig.")).toBeVisible();
      await expect(drawer.getByRole("button", { name: /^In Bearbeitung/ })).toBeVisible();

      // Status per Tastatur: Menü öffnen, Pfeile, Enter
      await drawer.getByRole("button", { name: /^In Bearbeitung/ }).focus();
      await page.keyboard.press("Enter");
      await page.getByRole("menuitemradio", { name: "Fehlalarm" }).focus();
      await page.keyboard.press("Enter");
      const dialog = page.getByRole("dialog", { name: "Status «Fehlalarm» setzen" });
      await dialog.getByLabel(/^Begründung/).fill("E2E: Testnetz");
      await dialog.getByRole("button", { name: "Mit Passkey bestätigen" }).click();
      await expect(page.getByText("Status «Fehlalarm» gesetzt, im Audit-Log vermerkt.")).toBeVisible();

      await drawer.getByLabel(/^Notiz hinzufügen/).fill("Nur Test-Fehlversuche");
      await drawer.getByRole("button", { name: "Notiz mit Passkey speichern" }).click();
      await expect(page.getByText("Notiz gespeichert.")).toBeVisible();
      await expect(drawer.getByText("Nur Test-Fehlversuche")).toBeVisible();

      const detail = await (await api.get(`/api/admin/auth-security/incidents/${incident.id}`)).json();
      expect(detail.status).toBe("false_positive");
      expect(detail.notes.map((item: { note: string }) => item.note)).toEqual(["E2E: Testnetz", "Nur Test-Fehlversuche"]);
      // Audit je Änderung, Notiztext nicht im Audit-Log
      const audit = JSON.stringify(await (await api.get("/api/admin/audit-log?action=admin.security_incident&limit=50")).json());
      expect(audit).toContain("admin.security_incident_status");
      expect(audit).not.toContain("Nur Test-Fehlversuche");

      // Ohne Passkey-Bestätigung keine Änderung
      const raw = await api.post(`/api/admin/auth-security/incidents/${incident.id}/notes`, { data: { note: "ohne Passkey" } });
      expect(raw.status()).toBe(403);

      // Keine Personendaten in der URL
      expect(page.url()).not.toMatch(/@|example|spray/);
      await page.keyboard.press("Escape");
    } finally {
      await passkey.save(passkeyFile);
      await api.dispose();
    }
  });

  test("Lagebild: Zeitraum in der URL, Tabellenalternativen, Vorfall-Markierung öffnet das Detail", async ({ page }) => {
    await page.goto("/admin/security");
    await expect(page.getByRole("heading", { name: "Lagebild", level: 1 })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Lage" })).toBeVisible();
    await page.getByRole("tab", { name: "7 T" }).click();
    await expect(page).toHaveURL(/range=7d/);
    const chart = page.getByRole("img", { name: "Anmeldungen im Zeitraum" });
    await expect(chart).toHaveAttribute("aria-describedby", /.+/);
    const marker = page.getByRole("button", { name: /^INC-\d{4,} öffnen, erkannt/ }).first();
    await marker.focus();
    await page.keyboard.press("Enter");
    await expect(page).toHaveURL(/incident=\d+/);
    await expect(page.locator("aside.admin-incident-detail")).toBeVisible();
    await page.getByRole("button", { name: "Daten als Tabelle" }).first().click();
    await expect(page.getByRole("columnheader", { name: "Abschnitt ab" })).toBeVisible();
    await page.getByRole("button", { name: "Live" }).click();
    await expect(page.getByRole("button", { name: "Pausiert" })).toHaveAttribute("aria-pressed", "false");
  });

  test("390 px ohne Überlaufen, Reiter überlappen nicht, axe ohne Befund", async ({ page }) => {
    const incidents = (await (await page.request.get("/api/admin/auth-security/incidents?status=all&limit=1")).json()) as { items: IncidentRow[] };
    const id = incidents.items[0]?.id;
    const paths = ["/admin/security", "/admin/security/incidents", "/admin/security/incidents?view=board"];
    if (id) paths.push(`/admin/security/incidents?incident=${id}`);
    for (const width of [1440, 390]) {
      await page.setViewportSize({ width, height: width > 600 ? 900 : 844 });
      for (const path of paths) {
        await page.goto(path);
        await page.waitForLoadState("networkidle").catch(() => undefined);
        await expect(page.getByText(/Application error|MISSING_MESSAGE/)).toHaveCount(0);
        if (width === 390) await noOverflowOrOverlap(page);
        else await axe(page);
      }
    }
  });

  test("Screenshots hell/dunkel bei 1440 und 390 px", async ({ browser }) => {
    mkdirSync(SHOTS, { recursive: true });
    const context = await browser.newContext({ storageState: authFiles.platformAdmin });
    const incidents = (await (await context.request.get("/api/admin/auth-security/incidents?status=all&limit=1")).json()) as { items: IncidentRow[] };
    await context.close();
    const id = incidents.items[0]?.id;
    const pages: [string, string][] = [
      ["lagebild", id ? `/admin/security?incident=${id}` : "/admin/security"],
      ["vorfaelle", "/admin/security/incidents?status=all"],
      ["vorfaelle-board", "/admin/security/incidents?view=board"],
    ];
    if (id) pages.push(["vorfall-detail", `/admin/security/incidents?status=all&incident=${id}`]);
    for (const scheme of ["light", "dark"] as const) {
      for (const width of [1440, 390]) {
        const shot = await browser.newContext({ storageState: authFiles.platformAdmin, colorScheme: scheme, viewport: { width, height: width > 600 ? 900 : 844 } });
        const page = await shot.newPage();
        for (const [name, path] of pages) {
          await page.goto(path);
          await page.waitForLoadState("networkidle").catch(() => undefined);
          await page.screenshot({ path: `${SHOTS}/${name}-${scheme}-${width}.png`, fullPage: true });
        }
        await shot.close();
      }
    }
  });
});
