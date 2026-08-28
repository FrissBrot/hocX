import { test, expect } from "@playwright/test";

test("publishes an assignment and uploads a PDF through the public UI", async ({ request, browser }) => {
  const suffix = Date.now();
  const session = await (await request.get("/api/auth/session")).json();
  const tenantId = session.current_tenant_id;
  const tenants = await (await request.get("/api/tenants")).json();
  const tenant = tenants.find((item: { id: string }) => item.id === tenantId);
  const oldSlug = tenant.public_slug;
  const tenantSlug = `e2e-${suffix}`;
  const assignmentSlug = `upload-${suffix}`;
  const today = new Date().toISOString().slice(0, 10);
  let eventId: string | undefined;
  let assignmentId: string | undefined;
  try {
    let response = await request.patch(`/api/tenants/${tenantId}`, { data: { public_slug: tenantSlug } });
    expect(response.ok(), await response.text()).toBeTruthy();
    response = await request.post("/api/events", { data: { event_date: today, title: `E2E Abgabe Element ${suffix}`, tag: `e2e-${suffix}` } });
    expect(response.ok(), await response.text()).toBeTruthy();
    eventId = (await response.json()).id;
    response = await request.post("/api/submission-assignments", { data: { title: `E2E Abgabe ${suffix}`, public_slug: assignmentSlug, source_type: "events", tag_filter: `e2e-${suffix}`, offset_days_before: 1, offset_days_after: 1, allowed_file_types: ["pdf"], max_files_per_element: 2, max_file_size_mb: 5, sort_order: "date" } });
    expect(response.ok(), await response.text()).toBeTruthy();
    assignmentId = (await response.json()).id;
    const elements = await (await request.get(`/api/submission-assignments/${assignmentId}/elements`)).json();
    expect(elements.length).toBe(1);

    const publicContext = await browser.newContext();
    const page = await publicContext.newPage();
    await page.goto(`${process.env.E2E_ABGABEBOX_BASE_URL}/${tenantSlug}/${assignmentSlug}/${encodeURIComponent(elements[0].element_ref)}`);
    await page.locator('input[type="file"]').setInputFiles({ name: "e2e-upload.pdf", mimeType: "application/pdf", buffer: Buffer.from("%PDF-1.4\n%%EOF\n") });
    await expect(page.getByText("Sicherheitscheck abgeschlossen")).toBeVisible();
    await page.getByRole("button", { name: /hochladen/i }).click();
    await expect(page.getByText("Abgabe erfolgreich")).toBeVisible();
    await publicContext.close();

    const received = await (await request.get(`/api/submission-assignments/${assignmentId}/elements`)).json();
    expect(received[0].files.length).toBeGreaterThan(0);
  } finally {
    if (assignmentId) await request.delete(`/api/submission-assignments/${assignmentId}`);
    if (eventId) await request.delete(`/api/events/${eventId}`);
    await request.patch(`/api/tenants/${tenantId}`, { data: { public_slug: oldSlug } });
  }
});
