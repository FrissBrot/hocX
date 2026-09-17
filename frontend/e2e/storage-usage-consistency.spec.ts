import { test, expect } from "@playwright/test";
import { authFiles } from "./auth";

// Regression guard for an audit fix (2026-09-17): the tenant-facing Speicher page and the
// admin tenant-settings "Speicher" tab used to each hand-roll their own usage bar/table, and
// had drifted apart (different quota denominator, no free-space segment on one of them) - an
// admin and the tenant itself could see different numbers for the exact same tenant. Both now
// render the same shared <StorageBreakdown> component (storage-usage-view.tsx) - this test
// pins that down at the E2E level so a future regression (one of the two call sites
// reverting to its own copy, or diverging props) actually gets caught.
test("tenant Speicher page and admin tenant-settings Speicher tab show the same bytes used", async ({ page, request, browser }) => {
  const session = await (await request.get("/api/auth/session")).json();
  const tenantName = session.current_tenant.name as string;

  const adminContext = await browser.newContext({ storageState: authFiles.platformAdmin });
  try {
    const adminPage = await adminContext.newPage();

    // This tenant is shared with every other e2e spec, some of which upload files to it
    // concurrently - reading the two values isn't atomic, so a third party's upload landing
    // strictly between the two reads would produce a false mismatch. Reload+re-read both
    // together until they agree (or the timeout proves a genuine, persistent divergence)
    // instead of comparing two one-shot snapshots.
    await expect(async () => {
      await page.goto("/storage");
      const tenantValue = (
        await page.locator(".stats-card", { hasText: "Belegt" }).locator(".stats-card-value").innerText()
      ).trim();

      await adminPage.goto("/admin/tenants");
      await adminPage.getByRole("row", { name: tenantName }).click();
      await adminPage.getByRole("tab", { name: "Speicher" }).click();
      const adminLine = await adminPage.getByText(/^Gesamt belegt: /).innerText();
      const adminValue = adminLine.replace(/^Gesamt belegt:\s*/, "").trim();

      expect(adminValue).toBe(tenantValue);
    }).toPass({ timeout: 30_000 });
  } finally {
    await adminContext.close();
  }
});
