import { test, expect } from "@playwright/test";

test("creates a todo and validates Markdown and registered PDF exports", async ({ request }) => {
  const suffix = Date.now();
  const todoResponse = await request.post("/api/todos", { data: { task: `E2E Export Todo ${suffix}` } });
  expect(todoResponse.ok(), await todoResponse.text()).toBeTruthy();
  const todo = await todoResponse.json();
  try {
    const params = { status: "all" };
    const markdown = await request.post("/api/documents/export", { data: { document_type: "todos", params, format: "markdown" } });
    expect(markdown.ok(), await markdown.text()).toBeTruthy();
    expect(await markdown.text()).toContain(`E2E Export Todo ${suffix}`);

    const pdf = await request.post("/api/documents/render", { data: { document_type: "todos", params }, timeout: 60_000 });
    expect(pdf.ok(), await pdf.text()).toBeTruthy();
    const metadata = await pdf.json();
    // Jedes PDF ist im Dokumentenregister erfasst und trägt Kurz-ID und Prüf-Link.
    expect(metadata.short_id).toMatch(/^[0-9A-F]{4}-[0-9A-F]{4}$/);
    expect(metadata.verify_url).toContain(`/verify?id=${metadata.id}`);
    const download = await request.get(metadata.content_url);
    expect(download.ok()).toBeTruthy();
    const body = await download.body();
    expect(body.subarray(0, 5).toString()).toBe("%PDF-");
    // keine Signatur mehr
    expect(body.includes("/ByteRange")).toBeFalsy();
  } finally {
    await request.delete(`/api/protocol-todos/${todo.id}`);
  }
});

test("export dialog and house styles show a live preview (light/dark)", async ({ page }) => {
  test.setTimeout(120_000);
  const suffix = Date.now();
  const todoResponse = await page.request.post("/api/todos", { data: { task: `E2E Vorschau Todo ${suffix}` } });
  expect(todoResponse.ok(), await todoResponse.text()).toBeTruthy();
  const todo = await todoResponse.json();
  try {
    for (const theme of ["light", "dark"]) {
      // Nur Desktop: die mobile Ansicht hat keinen Export-Dialog (Protokolle exportieren dort
      // direkt, Hausstile zeigen «nur am Desktop»).
      for (const width of [1440]) {
        await page.setViewportSize({ width, height: 1000 });
        await page.goto("/todos");
        await page.evaluate((value) => localStorage.setItem("hocx-theme", value), theme);
        await page.reload();
        const dialog = page.getByRole("dialog", { name: "Dokument erstellen" });
        // `next dev` kann beim ersten Aufruf per HMR neu mounten und den Dialog schliessen.
        await expect(async () => {
          if (!(await dialog.isVisible())) await page.getByRole("button", { name: /^Export(ieren …)?$/ }).first().click({ timeout: 5_000 });
          await expect(dialog.getByRole("img", { name: "Seite 1" })).toBeVisible({ timeout: 30_000 });
        }).toPass({ timeout: 90_000 });
        await page.screenshot({ path: `test-results/document-export-${theme}-${width}.png`, fullPage: true });
        await page.keyboard.press("Escape");
        await expect(dialog).toBeHidden();

        await page.goto("/settings");
        await expect(page.getByRole("region", { name: "Vorschau mit Musterdokument" }).getByRole("img", { name: "Seite 1" })).toBeVisible({ timeout: 60_000 });
        await page.screenshot({ path: `test-results/house-styles-${theme}-${width}.png`, fullPage: true });
      }
    }
  } finally {
    await page.request.delete(`/api/protocol-todos/${todo.id}`);
  }
});
