import type { APIRequestContext, APIResponse } from "@playwright/test";
import fs from "node:fs/promises";
import { tenantTotpFile } from "./auth";
import { currentTotpCode, totpCounter, waitForNextTotpWindow } from "./totp";

// Mandanten-Step-up (backend step_up_service.py): Ist die Anmeldung der Testsitzung älter als
// auth_step_up_admin_minutes (15 min), lehnt das Backend heikle Aktionen mit step_up_required ab.
// Im vollen Lauf hängt das von der Reihenfolge ab. Diese Hilfe führt die Anfrage aus und
// bestätigt bei step_up_required einmal per TOTP (Secret aus auth.setup.ts), dann erneut.
// Ein Code aus einem bereits verbrauchten 30-s-Fenster wird abgelehnt (Anti-Replay), darum
// höchstens drei Fenster.
export async function withTenantStepUp(
  context: APIRequestContext,
  email: string,
  call: () => Promise<APIResponse>,
): Promise<APIResponse> {
  const first = await call();
  if (first.ok() || !(await first.text()).includes("step_up_required")) return first;
  await confirmTenantStepUp(context, email);
  return call();
}

// Bestätigt die Sitzung vorab per TOTP, etwa vor einem Dialog, der sonst «Identität bestätigen»
// zeigen würde. Für den Browser page.request übergeben (teilt die Cookies der Seite).
export async function confirmTenantStepUp(context: APIRequestContext, email: string): Promise<void> {
  const secrets = JSON.parse(await fs.readFile(tenantTotpFile, "utf-8")) as Record<string, string>;
  const secret = secrets[email];
  if (!secret) throw new Error(`Kein TOTP-Secret für ${email} in ${tenantTotpFile}`);
  let lastError = "";
  for (let attempt = 0; attempt < 3; attempt += 1) {
    const counter = totpCounter();
    const confirm = await context.post("/api/auth/step-up", { data: { method: "totp", code: currentTotpCode(secret) } });
    if (confirm.ok()) return;
    lastError = await confirm.text();
    await waitForNextTotpWindow(counter);
  }
  throw new Error(`Step-up per TOTP für ${email} fehlgeschlagen: ${lastError}`);
}
