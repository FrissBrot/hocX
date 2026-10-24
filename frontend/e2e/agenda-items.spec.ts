import { test, expect, APIRequestContext } from "@playwright/test";

// Anliegen (agenda_item): im Popup erfassen (zuletzt gewählte Vorlage vorgewählt), erscheint
// danach ohne eigenen Block im nächsten Protokoll der Vorlage unter dem gewählten Traktandum.

async function json(request: APIRequestContext, method: "post" | "put", path: string, data: unknown) {
  const response = await request[method](path, { data });
  expect(response.ok(), `${method.toUpperCase()} ${path}: ${await response.text()}`).toBeTruthy();
  return response.status() === 204 ? null : response.json();
}

test("agenda item is created in the popup and listed in the next protocol", async ({ request, page }) => {
  test.setTimeout(180_000);
  const suffix = Date.now();
  const templates = await (await request.get("/api/templates")).json();
  expect(templates.length).toBeGreaterThan(0);
  const template = await json(request, "post", `/api/templates/${templates[0].id}/duplicate`, { name: `E2E Anliegen ${suffix}` });
  let protocolId: string | null = null;
  try {
    const protocol = await json(request, "post", "/api/protocols/from-template", {
      template_id: template.id,
      protocol_date: new Date(Date.now() + 2 * 86_400_000).toISOString().slice(0, 10),
      title: `E2E Anliegen-Protokoll ${suffix}`,
    });
    protocolId = protocol.id;
    // Vorlage wie nach einem früheren Erfassen merken - das Popup wählt sie vor.
    await json(request, "put", "/api/agenda-items/template-preference", { template_id: template.id });

    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.goto("/agenda");
    await expect(page.getByRole("heading", { name: "Anliegen", level: 1 })).toBeVisible({ timeout: 60_000 });
    const dialog = page.getByRole("dialog", { name: "Anliegen erfassen" });
    await expect(async () => {
      if (!(await dialog.isVisible())) await page.getByRole("button", { name: "Anliegen erfassen" }).first().click({ timeout: 5_000 });
      await expect(dialog).toBeVisible({ timeout: 5_000 });
    }).toPass({ timeout: 60_000 });
    await expect(dialog.getByText(`E2E Anliegen ${suffix}`)).toBeVisible();
    await dialog.getByLabel("Titel").fill(`Neue Kasse ${suffix}`);
    await page.screenshot({ path: "test-results/agenda-create-light-1440.png" });
    await dialog.getByRole("button", { name: "Erfassen" }).click();
    await expect(dialog).toBeHidden();
    const row = page.getByRole("row", { name: new RegExp(`Neue Kasse ${suffix}`) });
    await expect(row).toBeVisible();
    await expect(row).toContainText(`Protokoll ${protocol.protocol_number ?? ""}`.trim());
    await page.screenshot({ path: "test-results/agenda-list-light-1440.png", fullPage: true });

    const listed = await (await request.get(`/api/protocols/${protocolId}/agenda-items`)).json();
    expect(listed.map((item: { title: string }) => item.title)).toContain(`Neue Kasse ${suffix}`);

    await page.goto(`/protocols/${protocolId}`);
    await expect(page.getByLabel("Titel des Anliegens").first()).toHaveValue(`Neue Kasse ${suffix}`, { timeout: 60_000 });
    await page.screenshot({ path: "test-results/agenda-editor-light-1440.png" });
  } finally {
    if (protocolId) await request.delete(`/api/protocols/${protocolId}`);
    await request.delete(`/api/templates/${template.id}`);
  }
});
