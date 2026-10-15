import { test, expect, request as playwrightRequest } from "@playwright/test";

// Öffentliche Echtheitsprüfung in der Abgabebox: ein exportiertes PDF wird als «Original» erkannt,
// dieselbe Datei mit einem geänderten Byte als «nicht gefunden». Die Datei verlässt den Browser
// nie - geprüft wird, dass nur der Hash an den Endpoint geht.
test("verify page recognises the original and rejects a modified copy", async ({ page, request, browser }) => {
  test.setTimeout(150_000);
  const suffix = Date.now();
  const todoResponse = await request.post("/api/todos", { data: { task: `E2E Prüf-Todo ${suffix}` } });
  expect(todoResponse.ok(), await todoResponse.text()).toBeTruthy();
  const todo = await todoResponse.json();
  try {
    const rendered = await request.post("/api/documents/render", { data: { document_type: "todos", params: { status: "all" } }, timeout: 60_000 });
    expect(rendered.ok(), await rendered.text()).toBeTruthy();
    const metadata = await rendered.json();
    const pdf = await (await request.get(metadata.content_url)).body();
    const modified = Buffer.from(pdf);
    modified[modified.length - 10] ^= 0x01;

    const context = await browser.newContext({ baseURL: process.env.E2E_ABGABEBOX_BASE_URL, storageState: undefined });
    const verifyPage = await context.newPage();
    const posted: string[] = [];
    verifyPage.on("request", (req) => {
      if (req.url().includes("/api/public/verify")) posted.push(req.postData() ?? "");
    });
    try {
      for (const theme of ["light", "dark"]) {
        for (const width of [1440, 390]) {
          await verifyPage.setViewportSize({ width, height: 1000 });
          await verifyPage.goto(`/verify?id=${metadata.id}`);
          await verifyPage.evaluate((value) => localStorage.setItem("hocx-theme", value), theme);
          await verifyPage.reload();
          await expect(verifyPage.getByText(metadata.short_id).first()).toBeVisible();
          await verifyPage.screenshot({ path: `test-results/verify-start-${theme}-${width}.png`, fullPage: true });

          await verifyPage.locator("input[type=file]").setInputFiles({ name: "pendenzen.pdf", mimeType: "application/pdf", buffer: pdf });
          await expect(verifyPage.getByRole("heading", { name: "Original" })).toBeVisible({ timeout: 30_000 });
          await expect(verifyPage.getByText("unveränderte Kopie")).toBeVisible();
          await verifyPage.screenshot({ path: `test-results/verify-original-${theme}-${width}.png`, fullPage: true });

          await verifyPage.getByRole("button", { name: "Andere Datei prüfen" }).click();
          await verifyPage.locator("input[type=file]").setInputFiles({ name: "pendenzen-bearbeitet.pdf", mimeType: "application/pdf", buffer: modified });
          await expect(verifyPage.getByRole("heading", { name: "Nicht gefunden" })).toBeVisible({ timeout: 30_000 });
          await verifyPage.screenshot({ path: `test-results/verify-notfound-${theme}-${width}.png`, fullPage: true });
        }
      }
      // Nur Hash und Dokument-ID gehen an den Server, nie die Datei
      expect(posted.length).toBeGreaterThan(0);
      for (const body of posted) {
        expect(Object.keys(JSON.parse(body)).sort()).toEqual(["document_id", "sha256"]);
        expect(body.length).toBeLessThan(200);
      }
    } finally {
      await context.close();
    }

    // Endpoint direkt: kein Hinweis auf die Dokument-ID bei unbekanntem Hash
    const publicApi = await playwrightRequest.newContext({ baseURL: process.env.E2E_ABGABEBOX_BASE_URL });
    const miss = await publicApi.post("/api/public/verify", { data: { sha256: "f".repeat(64), document_id: metadata.id } });
    expect(await miss.json()).toEqual({ found: false });
    await publicApi.dispose();
  } finally {
    await request.delete(`/api/protocol-todos/${todo.id}`);
  }
});

test("authenticity settings (light/dark, 1440)", async ({ page }) => {
  test.setTimeout(90_000);
  for (const theme of ["light", "dark"]) {
    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.goto("/settings/verification");
    await page.evaluate((value) => localStorage.setItem("hocx-theme", value), theme);
    await page.reload();
    await expect(page.getByRole("heading", { name: "Echtheitsprüfung" })).toBeVisible();
    await expect(page.getByText("Vorschau der Prüfseite")).toBeVisible();
    await page.screenshot({ path: `test-results/verify-settings-${theme}-1440.png`, fullPage: true });
  }
});

test("verify page shows the organisation only when the tenant allows it", async ({ request, browser }) => {
  test.setTimeout(90_000);
  const settings = await (await request.get("/api/document-verification")).json();
  const rendered = await request.post("/api/documents/render", { data: { document_type: "events" }, timeout: 60_000 });
  expect(rendered.ok(), await rendered.text()).toBeTruthy();
  const metadata = await rendered.json();
  const pdf = await (await request.get(metadata.content_url)).body();
  const context = await browser.newContext({ baseURL: process.env.E2E_ABGABEBOX_BASE_URL, storageState: undefined });
  const page = await context.newPage();
  try {
    for (const show of [false, true]) {
      expect((await request.patch("/api/document-verification", { data: { show_identity: show } })).ok()).toBeTruthy();
      await page.goto("/verify");
      await page.locator("input[type=file]").setInputFiles({ name: "termine.pdf", mimeType: "application/pdf", buffer: pdf });
      await expect(page.getByRole("heading", { name: "Original" })).toBeVisible({ timeout: 30_000 });
      const createdBy = page.getByText(`Erstellt im hocX-Konto von ${settings.tenant_name}.`);
      if (show) {
        await expect(createdBy).toBeVisible();
        await page.screenshot({ path: "test-results/verify-identity-light-1440.png", fullPage: true });
      } else {
        await expect(createdBy).toHaveCount(0);
        await expect(page.getByText(settings.tenant_name, { exact: true })).toHaveCount(0);
      }
    }
  } finally {
    await request.patch("/api/document-verification", { data: { show_identity: settings.show_identity } });
    await context.close();
  }
});
