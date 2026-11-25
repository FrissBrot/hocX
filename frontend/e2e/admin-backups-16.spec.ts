import { test, expect, request, type APIRequestContext, type Page, type TestInfo } from "@playwright/test";
import { authFiles, platformAdminSpecPasskeyFile } from "./auth";

// Eigener Passkey dieser Spec (auth.ts, platformAdminSpecPasskeys): ein geteilter Signaturzähler
// über parallele Worker sperrt den Passkey als möglichen Klon.
const passkeyFile = platformAdminSpecPasskeyFile("admin-backups");
import { SoftPasskey, stepUpHeaders } from "./soft-passkey";

// Backups im Plattform-Admin (Redesign 1.6, Design «hocX Backups»): Reiter und Filter in der URL,
// Bedienung per Tastatur, Einstellungen mit Passkey, Zustände der Übersicht.
//
// Im E2E-Stack ist kein Backup-System eingerichtet (BACKUP_ENABLED fehlt): die Seite zeigt zuerst
// «nicht eingerichtet». Für die Zustände «In Ordnung», «Kritisch» und die Bildschirmfotos ersetzt
// die Route die Status-/Verlaufsantworten; die Seite lädt sie beim Zurückkehren in den Tab neu
// (useVisibleInterval). Passkey-Bestätigung wie security-admin-16.spec.ts.

const baseURL = process.env.PLAYWRIGHT_BASE_URL ?? "http://127.0.0.1:13000";
const origin = new URL(baseURL).origin;

async function softPasskeyStepUps(page: Page, purpose: string, pattern: RegExp): Promise<{ api: APIRequestContext; passkey: SoftPasskey }> {
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
  await page.route(pattern, async (route) => {
    const original = route.request();
    if (original.method() === "GET") return route.continue();
    const url = new URL(original.url());
    const body = original.postData() ?? "";
    const confirm = await stepUpHeaders(api, passkey!, origin, purpose, original.method(), url.pathname, body);
    const headers = Object.fromEntries(Object.entries(original.headers()).filter(([name]) => name.toLowerCase() !== "x-hocx-step-up"));
    await route.continue({ headers: { ...headers, ...confirm } });
  });
  return { api, passkey: passkey! };
}

const HOUR = 3_600_000;
const iso = (offsetMs: number) => new Date(Date.now() + offsetMs).toISOString();
const jobIds = Array.from({ length: 8 }, (_, index) => `0e742723-9159-46cb-9d6d-ce550821b9${String(index).padStart(2, "0")}`);

function backupSet(index: number, overrides: Record<string, unknown> = {}) {
  return {
    id: `5b2f6d90-e1a2-4c3b-8d7f-6e5a4b3c2d${String(index).padStart(2, "0")}`, archive_name: `hocx-rp-20261124T1215${String(index).padStart(2, "0")}Z-0e742723915946cb9d6d6ce550821b97`,
    state: "completed", trigger: "schedule", protected: index === 2, protected_reason: null, snapshot_at: iso(-(index * 6 + 3.5) * HOUR), finished_at: iso(-(index * 6 + 3.5) * HOUR),
    app_version: "1.6.0", alembic_revision: "0280_auth_event_subject_index", generation: 1, profile_name: "Lokales S3 (Garage)", profile_provider: "s3",
    db_dump_bytes: 6.4 * 1024 ** 2, object_count: 5208 - index * 3, object_bytes: 7.2 * 1024 ** 3, new_object_count: 3 + index, new_object_bytes: 4.1 * 1024 ** 2,
    deduplicated_bytes: 1.2 * 1024 ** 2, duration_seconds: 17, verify_state: index === 4 ? "verified" : "unverified", verified_at: null,
    restore_test_state: index === 4 ? "passed" : "untested", restore_tested_at: null, warnings: [], tenant_count: 3, reconstructed: false, job_id: jobIds[index], ...overrides,
  };
}

function job(index: number, overrides: Record<string, unknown> = {}) {
  return {
    id: jobIds[index], kind: "backup", trigger: "schedule", state: "completed", requested_by_email: null, created_at: iso(-(index * 6 + 3.5) * HOUR),
    started_at: iso(-(index * 6 + 3.5) * HOUR), finished_at: iso(-(index * 6 + 3.5) * HOUR), heartbeat_at: null, worker_active: false, attempt: 0,
    cancel_requested: false, progress: {}, error_code: null, error_message: null, warning_count: 0, duration_seconds: 17, backup_set: backupSet(index), summary: {}, ...overrides,
  };
}

function statusOf(kind: "ok" | "critical") {
  const repository = {
    ok: kind === "ok", checked_at: iso(-5 * 60_000), last_ok_at: iso(-HOUR), error_code: kind === "ok" ? null : "repository_unreachable", error: null,
    repository_id: "9f3c".padEnd(60, "0") + "a21e", encryption: "repokey-blake2", borg_version: "1.4.0", stored_bytes: 7.6 * 1024 ** 3, original_bytes: 302 * 1024 ** 3,
    deduplicated_bytes: 8.5 * 1024 ** 3, quota_bytes: 1024 ** 4, used_percent: 0.8, staging_free_bytes: 41.7 * 1024 ** 3, staging_total_bytes: 60 * 1024 ** 3,
    last_gc_at: null, last_verify_at: null, last_verify_ok: null, last_restore_test_at: null, last_restore_test_ok: null,
  };
  return {
    enabled: true, overall: kind, worker_alive: true, worker_heartbeat_at: iso(-60_000),
    problems: kind === "ok" ? [] : [
      { code: "repository_unreachable", severity: "critical", params: { errorCode: "borg_connection_lost" } },
      { code: "overdue", severity: "critical", params: { hours: 15 } },
    ],
    last_success: backupSet(0), last_failure: kind === "ok" ? null : job(1, { state: "failed", error_code: "borg_repository_unreachable", backup_set: null }),
    next_backup_at: iso(2.4 * HOUR), restore_point_count: 42, protected_count: 2, latest_object_bytes: 7.2 * 1024 ** 3, latest_db_bytes: 6.4 * 1024 ** 2,
    repository, last_verified_at: iso(-6 * 24 * HOUR), last_verified_archive: backupSet(4).archive_name, last_restore_test_at: iso(-6 * 24 * HOUR),
    last_restore_test_archive: backupSet(4).archive_name, current_job: null, current_restore: null,
  };
}

async function mockBackupApi(page: Page, kind: "ok" | "critical") {
  const history = [
    job(0), job(1, kind === "critical" ? { state: "failed", error_code: "borg_repository_unreachable", backup_set: null } : {}),
    job(2, { trigger: "pre_deploy" }), job(3, { state: "partial", backup_set: backupSet(3, { state: "partial", warnings: [{ code: "missing_objects", count: 2, items: [] }] }) }),
    job(4, { kind: "verify", trigger: "schedule", summary: { contents_checked: 200 } }),
    job(5, { kind: "retention", backup_set: null, summary: { removed: 3, kept: 42 } }),
    job(6, { kind: "restore_test", summary: { ok: true, contents_checked: 5002, application_ok: true } }),
  ];
  const counts = { completed: 5, partial: 1, failed: kind === "critical" ? 1 : 0 };
  await page.route(/\/api\/admin\/backups\/status$/, (route) => route.fulfill({ json: statusOf(kind) }));
  await page.route(/\/api\/admin\/backups\/sets(\?.*)?$/, (route) => route.fulfill({ json: [0, 2, 3, 4].map((index) => backupSet(index)) }));
  await page.route(/\/api\/admin\/backups\/sets\/[^/]+\/tenants$/, (route) => route.fulfill({ json: [
    { id: 11, public_id: null, name: "Pfadi Falkenstein", users: 48, objects: 2941, bytes: 3.9 * 1024 ** 3 },
    { id: 12, public_id: null, name: "Jungwacht Sursee", users: 31, objects: 1877, bytes: 2.6 * 1024 ** 3 },
  ] }));
  await page.route(/\/api\/admin\/backups(\?.*)?$/, (route) => {
    if (route.request().method() !== "GET") return route.continue();
    const url = new URL(route.request().url());
    const kindFilter = url.searchParams.get("kind");
    const items = history.filter((item) => !kindFilter || item.kind === kindFilter);
    return route.fulfill({ json: { items, total: items.length, offset: 0, limit: 25, counts } });
  });
  await page.route(/\/api\/admin\/backups\/[0-9a-f-]{36}$/, (route) => {
    const id = new URL(route.request().url()).pathname.split("/").pop();
    const item = history.find((entry) => entry.id === id) ?? history[0];
    const at = item.created_at;
    return route.fulfill({ json: { ...item, result: null, tenants: [
      { id: 11, public_id: null, name: "Pfadi Falkenstein", users: 48, objects: 2941, bytes: 3.9 * 1024 ** 3 },
      { id: 12, public_id: null, name: "Jungwacht Sursee", users: 31, objects: 1877, bytes: 2.6 * 1024 ** 3 },
    ], events: [
      { id: 1, created_at: at, level: "info", kind: "requested", actor_email: null, message: "Auftrag angelegt", details: {} },
      { id: 2, created_at: at, level: "info", kind: "hold_acquired", actor_email: null, message: null, details: {} },
      { id: 3, created_at: at, level: "info", kind: "captured", actor_email: null, message: null, details: {} },
      { id: 4, created_at: at, level: "info", kind: "restore_point_written", actor_email: null, message: null, details: {} },
    ] } });
  });
  await page.route(/\/api\/admin\/restores(\?.*)?$/, (route) => route.request().method() === "GET" ? route.fulfill({ json: [] }) : route.continue());
  await page.route(/\/api\/admin\/nav-counts$/, async (route) => {
    const real = await (await route.fetch()).json();
    await route.fulfill({ json: { ...real, backup_status: kind === "ok" ? null : "critical" } });
  });
}

async function refreshStatus(page: Page, heading: string) {
  // Neu laden wie beim Zurückkehren in den Tab (useVisibleInterval) - wiederholt, bis die Seite
  // hydriert ist und den Listener hat.
  await expect(async () => {
    await page.evaluate(() => document.dispatchEvent(new Event("visibilitychange")));
    await expect(page.getByRole("heading", { name: heading })).toBeVisible({ timeout: 1_500 });
  }).toPass({ timeout: 60_000 });
}

async function shoot(page: Page, testInfo: TestInfo, name: string) {
  for (const theme of ["light", "dark"] as const) {
    await page.evaluate((value) => document.documentElement.setAttribute("data-theme", value), theme);
    await page.screenshot({ path: testInfo.outputPath(`${name}-${theme}.png`), fullPage: true });
  }
  await page.evaluate(() => document.documentElement.setAttribute("data-theme", "light"));
}

test.describe("Backups 1.6", () => {
  test.use({ storageState: authFiles.platformAdmin });
  test.setTimeout(240_000);

  test("Reiter per Tastatur in der URL, Einstellungen nur mit Passkey", async ({ page }) => {
    const { api, passkey } = await softPasskeyStepUps(page, "backup-settings", /\/api\/admin\/backups\/settings$/);
    const before = await (await api.get("/api/admin/backups/settings")).json();
    const restoreBody = JSON.stringify({
      schedule_enabled: before.schedule_enabled, interval_hours: before.interval_hours, schedule_offset_minutes: before.schedule_offset_minutes,
      keep_within_days: before.keep_within_days, keep_daily: before.keep_daily, keep_weekly: before.keep_weekly, keep_monthly: before.keep_monthly,
      verify_interval_hours: before.verify_interval_hours, verify_sample_objects: before.verify_sample_objects,
      restore_test_interval_days: before.restore_test_interval_days, success_notification: before.success_notification,
    });
    try {
      await page.goto("/admin/backups");
      await expect(page.getByRole("heading", { name: "Backups", level: 1 })).toBeVisible();
      // Im E2E-Stack ist das Backup-System nicht eingerichtet - der Zustand bleibt sichtbar.
      await expect(page.getByText(/noch nicht eingerichtet/).first()).toBeVisible();

      await page.getByRole("tab", { name: "Übersicht" }).focus();
      await page.keyboard.press("ArrowRight");
      await expect(page.getByRole("tab", { name: "Verlauf" })).toHaveAttribute("aria-selected", "true");
      await expect(page).toHaveURL(/tab=history/);
      await page.reload();
      await expect(page.getByRole("tab", { name: "Verlauf" })).toHaveAttribute("aria-selected", "true");

      await page.goto("/admin/backups?tab=settings");
      const save = page.getByRole("button", { name: "Mit Passkey speichern" });
      await expect(save).toBeDisabled();
      const target = before.success_notification === "each" ? "Täglich" : "Jedes Backup";
      await page.getByRole("radio", { name: new RegExp(target) }).check();
      await expect(save).toBeEnabled();
      await save.click();
      await expect(page.getByText("Einstellungen gespeichert.")).toBeVisible();
      const after = await (await api.get("/api/admin/backups/settings")).json();
      expect(after.success_notification).toBe(before.success_notification === "each" ? "daily" : "each");
      await expect(save).toBeDisabled();
    } finally {
      // Derselbe Software-Passkey (Signaturzähler), sonst lehnt das Backend die Bestätigung ab.
      const headers = await stepUpHeaders(api, passkey, origin, "backup-settings", "PUT", "/api/admin/backups/settings", restoreBody);
      const restored = await api.put("/api/admin/backups/settings", { data: restoreBody, headers: { "Content-Type": "application/json", ...headers } });
      expect(restored.ok(), await restored.text()).toBe(true);
      await api.dispose();
    }
  });

  test("Übersicht: In Ordnung und Kritisch, Verlauf mit Details, Assistent und Bildschirmfotos", async ({ page }, testInfo) => {
    for (const [width, height] of [[1440, 1000], [390, 844]] as const) {
      await page.setViewportSize({ width, height });
      await page.unrouteAll({ behavior: "ignoreErrors" });
      await mockBackupApi(page, "ok");
      await page.goto("/admin/backups");
      await refreshStatus(page, "Alle Daten sind offsite gesichert.");
      await expect(page.getByRole("heading", { name: "Drei Nachweise" })).toBeVisible();
      await expect(page.getByRole("heading", { name: "Letzte 7 Tage" })).toBeVisible();
      // Echte Ersparnis über alle Punkte (302 GB → 7.6 GB), keine Fantasiezahl
      await expect(page.getByText("−97 %")).toBeVisible();
      expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
      await shoot(page, testInfo, `overview-ok-${width}`);

      await page.unrouteAll({ behavior: "ignoreErrors" });
      await mockBackupApi(page, "critical");
      await refreshStatus(page, "Backups laufen derzeit nicht zuverlässig.");
      await expect(page.getByText("Die Storage Box ist nicht erreichbar", { exact: true })).toBeVisible();
      await shoot(page, testInfo, `overview-critical-${width}`);

      await page.getByRole("button", { name: "Verlauf öffnen" }).click();
      await expect(page).toHaveURL(/tab=history/);
      await expect(page).toHaveURL(/state=failed/);
      await expect(page.getByRole("tab", { name: /Fehlgeschlagen/ })).toHaveAttribute("aria-selected", "true");
      await page.goto("/admin/backups?tab=history");
      await expect(page.getByText("3 Punkte entfernt")).toBeVisible();
      await shoot(page, testInfo, `history-${width}`);
      await page.getByRole("button", { name: /^Details: Backup/ }).first().click();
      const drawer = page.getByRole("dialog");
      await expect(drawer.getByRole("heading", { name: "Ereignisse" })).toBeVisible();
      await expect(page).toHaveURL(/job=/);
      await shoot(page, testInfo, `drawer-${width}`);
      await page.keyboard.press("Escape");
      await expect(page).not.toHaveURL(/job=/);

      await page.getByRole("tab", { name: "Wiederherstellung" }).click();
      await page.getByRole("radio", { name: /hocx-rp-20261124T121500Z/ }).check();
      await page.getByRole("radio", { name: /Pfadi Falkenstein/ }).check();
      await expect(page.getByLabel("Name des neuen Mandanten")).toHaveValue("Pfadi Falkenstein (Wiederherstellung)");
      await shoot(page, testInfo, `restore-${width}`);

      await page.getByRole("tab", { name: "Einstellungen" }).click();
      await expect(page.getByRole("heading", { name: "Zeitplan" })).toBeVisible();
      await shoot(page, testInfo, `settings-${width}`);
      expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
    }
  });
});
