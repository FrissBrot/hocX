import { test, expect } from "@playwright/test";
import { renderPdf } from "./render-pdf";

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

    const metadata = await renderPdf(request, { document_type: "todos", params });
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

test("export dialog, template library, brand studio and designer render (light/dark)", async ({ page }) => {
  test.setTimeout(240_000);
  const suffix = Date.now();
  const todoResponse = await page.request.post("/api/todos", { data: { task: `E2E Vorschau Todo ${suffix}` } });
  expect(todoResponse.ok(), await todoResponse.text()).toBeTruthy();
  const todo = await todoResponse.json();
  try {
    for (const theme of ["light", "dark"]) {
      // Nur Desktop: der Designer ist bewusst nur am Desktop verfügbar.
      for (const width of [1440]) {
        await page.setViewportSize({ width, height: 1000 });
        await page.goto("/todos");
        await page.evaluate((value) => localStorage.setItem("hocx-theme", value), theme);
        await page.reload();
        const dialog = page.getByRole("dialog", { name: "Dokument exportieren" });
        // `next dev` kann beim ersten Aufruf per HMR neu mounten und den Dialog schliessen.
        await expect(async () => {
          if (!(await dialog.isVisible())) await page.getByRole("button", { name: /^Export(ieren)?$/ }).first().click({ timeout: 5_000 });
          await expect(dialog.getByRole("img", { name: "Seite 1" })).toBeVisible({ timeout: 30_000 });
        }).toPass({ timeout: 90_000 });
        await page.screenshot({ path: `test-results/document-export-${theme}-${width}.png`, fullPage: true });
        await page.keyboard.press("Escape");
        await expect(dialog).toBeHidden();

        await page.goto("/documents");
        await expect(page.getByRole("heading", { name: "Dokumente", level: 1 })).toBeVisible();
        await expect(page.getByRole("region", { name: "Pendenzenliste" })).toBeVisible({ timeout: 60_000 });
        await page.screenshot({ path: `test-results/document-library-${theme}-${width}.png`, fullPage: true });

        await page.goto("/documents/brand");
        await expect(page.getByRole("region", { name: "Vorschau" }).getByRole("img", { name: "Seite 1" })).toBeVisible({ timeout: 60_000 });
        await page.screenshot({ path: `test-results/document-brand-${theme}-${width}.png`, fullPage: true });

        // Designer einer Systemvorlage (schreibgeschützt) mit Arbeitsfläche und echter Vorschau
        const templates = await (await page.request.get("/api/document-templates?document_type=todos")).json();
        const system = templates.find((item: { system_key: string | null }) => item.system_key === "todos_standard");
        await page.goto(`/documents/templates/${system.id}`);
        await expect(page.getByRole("main", { name: "Arbeitsfläche" })).toBeVisible({ timeout: 60_000 });
        await page.screenshot({ path: `test-results/document-designer-${theme}-${width}.png` });
        await page.getByRole("radio", { name: "Geteilt" }).click();
        await expect(page.getByRole("region", { name: "Vorschau" }).getByRole("img", { name: "Seite 1" })).toBeVisible({ timeout: 60_000 });
        await page.screenshot({ path: `test-results/document-designer-split-${theme}-${width}.png` });
      }
      // Smartphone: das Document Studio ist bewusst nur am Desktop bedienbar (Hinweis mit Link)
      await page.setViewportSize({ width: 390, height: 844 });
      await page.goto("/documents");
      await expect(page.getByRole("heading", { name: "Vorlagen", level: 1 })).toBeVisible({ timeout: 60_000 });
      await expect(page.getByText("Diesen Bereich bearbeitest du am Computer.", { exact: false })).toBeVisible();
      await page.screenshot({ path: `test-results/document-studio-${theme}-390.png` });
    }
  } finally {
    await page.request.delete(`/api/protocol-todos/${todo.id}`);
  }
});
