import { test, expect, APIRequestContext, Page } from "@playwright/test";

// Termin-Blöcke im Protokoll-Editor: automatisch pro Termin erzeugte Blöcke laufen als eine
// Gruppe mit Termin-Karten, lassen sich einzeln entfernen und über «Termine wählen» (nach Monat)
// an- und abwählen. Screenshots Light/Dark bei 1440 px (unter 900 px gilt der eigene mobile
// Editor, mobile-protocol-editor.tsx).

async function json(request: APIRequestContext, method: "post" | "patch", path: string, data: unknown) {
  const response = await request[method](path, { data });
  expect(response.ok(), `${method.toUpperCase()} ${path}: ${await response.text()}`).toBeTruthy();
  return response.status() === 204 ? null : response.json();
}

function isoInDays(days: number) {
  return new Date(Date.now() + days * 86_400_000).toISOString().slice(0, 10);
}

async function shot(page: Page, name: string) {
  for (const theme of ["light", "dark"] as const) {
    await page.evaluate((value) => document.documentElement.setAttribute("data-theme", value), theme);
    await page.screenshot({ path: `test-results/event-series-${name}-${theme}-${page.viewportSize()?.width}.png` });
  }
  await page.evaluate(() => document.documentElement.setAttribute("data-theme", "light"));
}

test("event blocks are grouped per event, can be removed and chosen by month", async ({ request, page }) => {
  test.setTimeout(240_000);
  const suffix = Date.now();
  const tag = `Training${suffix}`;
  const protocolDate = isoInDays(7);
  const events = [];
  for (const [days, title] of [[0, "Hallentraining"], [14, "Techniktraining"], [21, "Hallentraining"]] as const) {
    events.push(await json(request, "post", "/api/events", { event_date: isoInDays(7 + days), tag, title, location: "Turnhalle Dorf" }));
  }
  const later = await json(request, "post", "/api/events", { event_date: isoInDays(7 + 70), tag, title: "Jahresabschluss-Training", location: "Turnhalle Dorf" });
  const template = await json(request, "post", "/api/templates", {
    name: `E2E Termin-Blöcke ${suffix}`, protocol_number_pattern: "E2E-{n}", title_pattern: "Hock {dd.mm.yyyy}", auto_create_next_protocol: false,
  });
  const definition = await json(request, "post", "/api/element-definitions", {
    title: `Trainings-Rückblick ${suffix}`,
    blocks: [{
      id: 1, title: "Rückblick", element_type_id: 1, render_type_id: 2, sort_index: 10,
      configuration_json: {
        repeat_source: "event",
        repeat_event_filter: { tags: [tag], title: "", description: "", range: { mode: "window", start_days: 0, end_days: 30 }, cycle: null, use_column_filter: false, sort: "asc", limit: null },
      },
    }, {
      id: 2, title: "Notiz zum Termin", element_type_id: 1, render_type_id: 2, sort_index: 20,
      configuration_json: {
        repeat_source: "event",
        sync_target_field: "description",
        repeat_event_filter: { tags: [tag], title: "", description: "", range: { mode: "window", start_days: 0, end_days: 30 }, cycle: null, use_column_filter: false, sort: "asc", limit: null },
      },
    }],
  });
  await json(request, "post", `/api/templates/${template.id}/elements`, { element_definition_id: definition.id, sort_index: 10 });
  let protocolId: string | null = null;
  try {
    const protocol = await json(request, "post", "/api/protocols/from-template", { template_id: template.id, protocol_date: protocolDate, title: `E2E Termin-Blöcke ${suffix}` });
    protocolId = protocol.id;

    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.goto(`/protocols/${protocolId}`);
    const series = page.locator(".event-series");
    await expect(series).toBeVisible({ timeout: 60_000 });
    await expect(series.getByText(`Pro Termin · Tag «${tag}»`)).toBeVisible();
    await expect(series.getByText("3 Termine", { exact: false })).toBeVisible();
    await expect(series.locator(".event-series-card")).toHaveCount(3);
    // Zwei Blöcke je Termin in einer Karte, der Block mit Speicherziel ist als verknüpft markiert
    await expect(series.locator(".event-series-card").first().getByText("Notiz zum Termin")).toBeVisible();
    await expect(series.locator(".event-series-card").first().getByText("aus Termin")).toBeVisible();

    // Entfernen: Rückfrage bietet den passenden Tag an, danach fehlt die Karte, Zähler sinkt
    await series.getByRole("button", { name: /^Entfernen/ }).nth(1).click();
    const remove = page.getByRole("dialog", { name: "Termin entfernen" });
    await expect(remove.getByText(`Tag «${tag}» vom Termin entfernen`)).toBeVisible();
    await shot(page, "remove");
    await remove.getByRole("button", { name: "Entfernen", exact: true }).click();
    await expect(remove).toBeHidden();
    await expect(series.locator(".event-series-card")).toHaveCount(2);
    await expect(series.getByText("Techniktraining")).toHaveCount(0);
    await expect(series.getByText("2 Termine", { exact: false })).toBeVisible();
    await shot(page, "group");

    // Termine wählen: späterer Termin im Reiter «Alle», anhaken ergibt einen weiteren Block
    await series.getByRole("button", { name: "Termine wählen" }).click();
    const dialog = page.getByRole("dialog", { name: "Termine wählen" });
    await expect(dialog).toBeVisible();
    await dialog.getByRole("tab", { name: "Alle" }).click();
    await expect(dialog.getByText("Jahresabschluss-Training")).toBeVisible({ timeout: 30_000 });
    await shot(page, "picker");
    await dialog.getByRole("button", { name: /Jahresabschluss-Training/ }).first().click();
    await expect(dialog.getByText("ergibt 3 Blöcke")).toBeVisible();
    await dialog.getByRole("button", { name: "Schliessen" }).click();
    await expect(series.locator(".event-series-card")).toHaveCount(3);
    await expect(series.getByText("Jahresabschluss-Training")).toBeVisible();
  } finally {
    if (protocolId) await request.delete(`/api/protocols/${protocolId}`);
    await request.delete(`/api/templates/${template.id}`);
    await request.delete(`/api/element-definitions/${definition.id}`);
    for (const event of [...events, later]) await request.delete(`/api/events/${event.id}`);
  }
});
