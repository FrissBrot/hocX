import { test, expect, request, type APIRequestContext, type Page } from "@playwright/test";

import { authFiles, platformAdminSpecPasskeyFile } from "./auth";
import { SoftPasskey, stepUpHeaders } from "./soft-passkey";

// Plattform-Admin › Datei-Importe: Notfall-Abbruch nur mit Passkey-Bestätigung (Security-Review 1.6,
// Zweck «cloud-import-cancel»). Läuft im Projekt «tenant-import» (legt einen Import im Demo-Mandanten an).
//
// Wie security-admin-16.spec.ts: die Oberfläche läuft echt (step-up/start, navigator.credentials,
// Anfrage mit Header); die Route ersetzt den Header durch eine echte Bestätigung des eigenen
// Software-Passkeys dieser Spec (auth.ts, platformAdminSpecPasskeys), gebunden an Methode, Pfad und Body.

const baseURL = process.env.PLAYWRIGHT_BASE_URL ?? "http://127.0.0.1:13000";
const origin = new URL(baseURL).origin;
const passkeyFile = platformAdminSpecPasskeyFile("cloud-imports");
const OPEN = ["draft", "listing", "ready", "queued", "running", "needs_reauth"];

async function tenantApi(): Promise<APIRequestContext> {
  return request.newContext({ baseURL, storageState: authFiles.admin, extraHTTPHeaders: { Origin: origin } });
}

async function cancelOpenImports(api: APIRequestContext) {
  const jobs = (await (await api.get("/api/cloud-import/jobs")).json()) as { id: string; status: string }[];
  for (const job of jobs.filter((entry) => OPEN.includes(entry.status))) {
    await api.post(`/api/cloud-import/jobs/${job.id}/cancel`);
  }
}

async function confirmStepUpsWithSoftPasskey(page: Page): Promise<APIRequestContext> {
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
  await page.route(/\/api\/admin\/cloud-imports\/[^/]+\/cancel$/, async (route) => {
    const original = route.request();
    const url = new URL(original.url());
    const confirm = await stepUpHeaders(api, passkey!, origin, "cloud-import-cancel", original.method(), url.pathname, original.postData() ?? "");
    const headers = Object.fromEntries(Object.entries(original.headers()).filter(([name]) => name.toLowerCase() !== "x-hocx-step-up"));
    await route.continue({ headers: { ...headers, ...confirm } });
  });
  return api;
}

test.describe("Plattform-Admin: Datei-Importe", () => {
  test.use({ storageState: authFiles.platformAdmin });

  test("Notfall-Abbruch verlangt eine Passkey-Bestätigung", async ({ page }) => {
    test.setTimeout(120_000);
    const tenant = await tenantApi();
    const admin = await confirmStepUpsWithSoftPasskey(page);
    try {
      await cancelOpenImports(tenant);
      const created = await tenant.post("/api/cloud-import/jobs", { data: { source: "zip" } });
      expect(created.ok(), await created.text()).toBeTruthy();
      const job = (await created.json()) as { id: string };
      const session = (await (await tenant.get("/api/auth/session")).json()) as { current_tenant: { name: string } };

      // Ohne Bestätigung lehnt das Backend ab
      const direct = await admin.post(`/api/admin/cloud-imports/${job.id}/cancel`);
      expect(direct.status()).toBe(403);
      expect(((await direct.json()) as { detail: { code: string } }).detail.code).toBe("admin_step_up_required");

      await page.goto("/admin/cloud-imports");
      await expect(page.getByRole("heading", { name: "Datei-Importe" }).first()).toBeVisible();
      const row = page.getByRole("row").filter({ hasText: session.current_tenant.name });
      await expect(row).toHaveCount(1);
      await row.getByRole("button", { name: "Abbrechen" }).click();
      await page.getByRole("alertdialog").getByRole("button", { name: "Import abbrechen" }).click();
      await expect(page.getByText("Der Import wird abgebrochen.")).toBeVisible();

      const after = (await (await tenant.get(`/api/cloud-import/jobs/${job.id}`)).json()) as { status: string };
      expect(after.status).toBe("cancelled");
    } finally {
      await cancelOpenImports(tenant);
      await tenant.dispose();
      await admin.dispose();
    }
  });
});
