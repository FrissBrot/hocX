import { test, expect, APIRequestContext } from "@playwright/test";

async function json(request: APIRequestContext, method: "post" | "patch", path: string, data: unknown) {
  const response = await request[method](path, { data });
  expect(response.ok(), `${method.toUpperCase()} ${path}: ${await response.text()}`).toBeTruthy();
  return response.json();
}

test("creates, reads, edits and deletes core entities", async ({ request, page }) => {
  const suffix = Date.now();
  const cleanup: Array<[string, string]> = [];
  try {
    const participant = await json(request, "post", "/api/participants", { display_name: `E2E Teilnehmer ${suffix}`, email: `e2e-${suffix}@example.invalid` });
    cleanup.push(["participant", participant.id]);
    const changedParticipant = await json(request, "patch", `/api/participants/${participant.id}`, { display_name: `E2E Teilnehmer geändert ${suffix}` });
    expect(changedParticipant.display_name).toContain("geändert");

    const list = await json(request, "post", "/api/lists", { name: `E2E Liste ${suffix}`, column_one_title: "Name", column_one_value_type: "text", column_two_title: "Info", column_two_value_type: "text" });
    cleanup.push(["list", list.id]);
    const entry = await json(request, "post", `/api/lists/${list.id}/entries`, { column_one_value: { text: "Alpha" }, column_two_value: { text: "Beta" } });
    expect((await (await request.get(`/api/lists/${list.id}/entries`)).json()).some((item: { id: string }) => item.id === entry.id)).toBeTruthy();

    const session = await (await request.get("/api/auth/session")).json();
    const tenantId = session.current_tenant.id;
    const user = await json(request, "post", "/api/users", { first_name: "E2E", last_name: "User", display_name: `E2E User ${suffix}`, email: `user-${suffix}@example.invalid`, password: "E2E-Secure-Password-123!", default_tenant_id: tenantId, memberships: [{ tenant_id: tenantId, role_code: "reader" }] });
    cleanup.push(["user", user.id]);

    const templates = await (await request.get("/api/templates")).json();
    expect(templates.length).toBeGreaterThan(0);
    const duplicate = await json(request, "post", `/api/templates/${templates[0].id}/duplicate`, { name: `E2E Vorlage ${suffix}` });
    cleanup.push(["template", duplicate.id]);
    const protocolResult = await json(request, "post", "/api/protocols/from-template", { template_id: duplicate.id, protocol_date: new Date().toISOString().slice(0, 10), title: `E2E Protokoll ${suffix}` });
    cleanup.push(["protocol", protocolResult.protocol_id]);

    await page.goto("/participants");
    await expect(page.getByText(`E2E Teilnehmer geändert ${suffix}`)).toBeVisible();
  } finally {
    for (const [type, id] of cleanup.reverse()) {
      const paths: Record<string, string> = { participant: `/api/participants/${id}`, list: `/api/lists/${id}`, user: `/api/users/${id}`, template: `/api/templates/${id}`, protocol: `/api/protocols/${id}` };
      await request.delete(paths[type]);
    }
  }
});

test("event edit/delete lifecycle survives a reload", async ({ request, page }) => {
  const suffix = Date.now();
  const event = await json(request, "post", "/api/events", { event_date: new Date().toISOString().slice(0, 10), title: `E2E Termin ${suffix}`, tag: "e2e" });
  try {
    await json(request, "patch", `/api/events/${event.id}`, { title: `E2E Termin geändert ${suffix}` });
    await page.goto("/events");
    await page.reload();
    await expect(page.getByText(`E2E Termin geändert ${suffix}`)).toBeVisible();
  } finally {
    expect((await request.delete(`/api/events/${event.id}`)).ok()).toBeTruthy();
  }
});
