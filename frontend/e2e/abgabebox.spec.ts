import { test, expect } from "@playwright/test";

test("publishes an assignment and uploads a PDF through the public UI", async ({ request, browser }) => {
  const suffix = Date.now();
  const session = await (await request.get("/api/auth/session")).json();
  const tenantId = session.current_tenant.id;
  const tenants = await (await request.get("/api/tenants")).json();
  const tenant = tenants.find((item: { id: string }) => item.id === tenantId);
  const oldSlug = tenant.public_slug;
  const tenantSlug = `e2e-${suffix}`;
  const assignmentSlug = `upload-${suffix}`;
  const today = new Date().toISOString().slice(0, 10);
  let eventId: string | undefined;
  let assignmentId: string | undefined;
  try {
    // patch_tenant (backend/app/api/routes/tenants.py) takes Form(...) fields, not JSON -
    // it also accepts an optional profile_image file upload, so the real admin UI always
    // submits FormData (tenant-settings-manager.tsx/admin-tenant-settings-modal.tsx). A
    // JSON body silently leaves every field at its Form(default=None) - HTTP 200, but
    // public_slug never actually changes, which then 404s the public upload page below.
    let response = await request.patch(`/api/tenants/${tenantId}`, { multipart: { public_slug: tenantSlug } });
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
    // .env.e2e.example deliberately leaves FRIENDLY_CAPTCHA_SITEKEY empty (no real captcha
    // configured for e2e), so upload-form.tsx shows its dev/test placeholder instead of the
    // "✓ Sicherheitscheck abgeschlossen" text a real sitekey would produce - the token
    // exchange still happens in the background either way (see that component's comment).
    await expect(page.getByText("kein FriendlyCaptcha konfiguriert")).toBeVisible();
    // The submit button's label is "Abgeben" (upload-form.tsx) - /hochladen/i only ever
    // matches its loading state ("Wird hochgeladen…", after the click) or the unrelated
    // "Weitere Datei hochladen" button for attaching more files, so this selector never
    // resolved and the click hung until the test timeout.
    await page.getByRole("button", { name: "Abgeben" }).click();
    await expect(page.getByText("Abgabe erfolgreich")).toBeVisible();
    await publicContext.close();

    const received = await (await request.get(`/api/submission-assignments/${assignmentId}/elements`)).json();
    expect(received[0].files.length).toBeGreaterThan(0);
  } finally {
    if (assignmentId) await request.delete(`/api/submission-assignments/${assignmentId}`);
    if (eventId) await request.delete(`/api/events/${eventId}`);
    // update_tenant treats an absent/None public_slug as "leave unchanged", not "clear" -
    // there's no way to restore a previously-empty slug through this endpoint, so only
    // bother reverting when there actually was a prior value to go back to.
    if (oldSlug) await request.patch(`/api/tenants/${tenantId}`, { multipart: { public_slug: oldSlug } });
  }
});
