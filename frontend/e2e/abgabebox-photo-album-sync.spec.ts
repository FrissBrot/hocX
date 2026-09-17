import { test, expect, request as playwrightRequest } from "@playwright/test";
import path from "node:path";
import { authFiles } from "./auth";

// Abgabebox photo -> auto-album sync, end to end across both services: a visitor uploads a
// photo through the public Abgabebox upload page (abgabebox-frontend + abgabebox-backend,
// writing into the same Postgres database via the least-privileged hocx_abgabebox role),
// main.py's abgabebox_rescan_loop promotes it from quarantine to a clean StoredFile, and
// main.py's photo_album_sync_loop (photo_album_service.sync_submission_uploads) then folds it
// into that Abgabe's auto-generated album. This whole feature was dead from the 1.1 merge
// until the 2026-09-17 audit fix (see backend/tests/test_app_lifespan_smoke.py's docstring) -
// every existing test for it (test_photo_album_sync.py) calls sync_submission_uploads()
// directly, never through the actual loop, and nothing anywhere drove a real public upload
// into it. This is the one test that proves the whole chain at the app level.
//
// KNOWN BLOCKER (as of 2026-09-17, unresolved): this currently fails before it ever reaches
// the album-sync assertions. upload-form.tsx's mount-time useEffect that auto-bypasses the
// captcha widget in dev/test (`if (!sitekey) handleSolved(...)`) never actually fires in this
// stack's abgabebox-frontend dev server - confirmed via isolated repro (goto + 15s wait, zero
// network requests to .../captcha-verify), while other client interactions on the same page
// (the drop-zone's onClick opening a filechooser) work fine, and the captcha-verify endpoint
// itself answers correctly when called directly. Root cause not found - needs a real
// browser/devtools session against this Next.js/Turbopack dev setup, not something diagnosable
// blind from a CLI sandbox. Do not "fix" this test by working around the missing captcha
// token (e.g. driving the upload via a raw API call instead of the real page) without
// checking with whoever picks this up - that would quietly drop this test back to what
// gap analysis already flagged as missing: real UI-level coverage of this exact flow.
test("a public Abgabebox photo upload is folded into its Abgabe-Element auto-album", async ({ page, browser }) => {
  test.setTimeout(120_000);
  const api = await playwrightRequest.newContext({ baseURL: process.env.PLAYWRIGHT_BASE_URL, storageState: authFiles.admin });
  const suffix = `${Date.now()}`;
  let tenantSlug: string | undefined;
  let assignmentId: string | undefined;
  let eventId: string | undefined;

  try {
    const session = await (await api.get("/api/auth/session")).json();
    tenantSlug = session.current_tenant.public_slug as string | null ?? undefined;
    if (!tenantSlug) {
      tenantSlug = `e2e-tenant-${suffix}`;
      const slugged = await api.patch(`/api/tenants/${session.current_tenant.id}`, { multipart: { public_slug: tenantSlug } });
      expect(slugged.ok(), await slugged.text()).toBeTruthy();
    }

    const tag = `e2e-abgabe-${suffix}`;
    const createdEvent = await api.post("/api/events", {
      data: { event_date: new Date().toISOString().slice(0, 10), title: `E2E Termin ${suffix}`, tag },
    });
    expect(createdEvent.ok(), await createdEvent.text()).toBeTruthy();
    const event = await createdEvent.json();
    eventId = event.id;

    const assignmentSlug = `e2e-abgabe-${suffix}`;
    const createdAssignment = await api.post("/api/submission-assignments", {
      data: {
        title: `E2E Abgabe ${suffix}`,
        public_slug: assignmentSlug,
        source_type: "events",
        tag_filter: tag,
        offset_days_before: 30,
        offset_days_after: 30,
        allowed_file_types: ["jpg", "jpeg", "png"],
        max_files_per_element: 10,
        max_file_size_mb: 10,
        sort_order: "date",
      },
    });
    expect(createdAssignment.ok(), await createdAssignment.text()).toBeTruthy();
    const assignment = await createdAssignment.json();
    assignmentId = assignment.id;

    // Public, unauthenticated upload through the real Abgabebox page - a separate frontend
    // service/origin, so a fresh, storageState-less browser context (not `page`, which
    // carries the main app's admin session).
    const publicContext = await browser.newContext({ baseURL: process.env.E2E_ABGABEBOX_BASE_URL, storageState: undefined });
    try {
      const publicPage = await publicContext.newPage();
      const elementsResponse = await publicContext.request.get(
        `/api/public/${tenantSlug}/assignments/${assignmentSlug}/elements`
      );
      expect(elementsResponse.ok(), await elementsResponse.text()).toBeTruthy();
      const elements = await elementsResponse.json();
      expect(elements.length).toBeGreaterThan(0);
      const elementRef = elements[0].element_ref as string;

      await publicPage.goto(`/${tenantSlug}/${assignmentSlug}/${elementRef}`);
      await publicPage.waitForLoadState("networkidle");
      // A real filechooser interaction (via the visible drop-zone's own click handler),
      // not a direct setInputFiles() on the hidden #files input - see
      // gallery-upload-cycle-target.spec.ts's note on the same input-vs-state quirk.
      const fileChooserPromise = publicPage.waitForEvent("filechooser");
      await publicPage.locator(".drop-zone").click();
      const fileChooser = await fileChooserPromise;
      await fileChooser.setFiles(path.resolve("e2e/fixtures/photos/sample.png"));
      await expect(publicPage.getByRole("button", { name: "Abgeben" })).toBeEnabled();
      await publicPage.getByRole("button", { name: "Abgeben" }).click();
      await expect(publicPage.getByText("Abgabe erfolgreich")).toBeVisible();
    } finally {
      await publicContext.close();
    }

    // Stage 1: promote the upload out of quarantine (scan_status pending -> clean) via the
    // same manual per-assignment trigger the Abgabebox admin screen itself uses - a real,
    // already-existing feature, not something added for this test. Faster and more
    // deterministic than waiting out abgabebox_rescan_loop's own interval.
    const rescan = await api.post(`/api/submission-assignments/${assignmentId}/rescan-pending`);
    expect(rescan.ok(), await rescan.text()).toBeTruthy();
    const rescanResult = await rescan.json();
    expect(rescanResult.clean).toBeGreaterThan(0);

    // Stage 2: photo_album_sync_loop has no manual trigger (see docker-compose.e2e.yml's
    // PHOTO_ALBUM_SYNC_INTERVAL_MINUTES override) - poll for the real background loop's own
    // next tick to fold the now-clean file into its Abgabe-Element album.
    await expect
      .poll(
        async () => {
          const albums = await (await api.get("/api/files/albums")).json();
          const elementAlbum = albums.find(
            (album: { kind: string; name: string }) => album.kind === "submission_element" && album.name.includes(`E2E Abgabe ${suffix}`)
          );
          return elementAlbum?.photo_count ?? 0;
        },
        { message: "waiting for photo_album_sync_loop to fold the upload into its Abgabe-Element album", timeout: 90_000, intervals: [2_000, 5_000] }
      )
      .toBeGreaterThan(0);
  } finally {
    if (assignmentId) await api.delete(`/api/submission-assignments/${assignmentId}`).catch(() => {});
    if (eventId) await api.delete(`/api/events/${eventId}`).catch(() => {});
    await api.dispose();
  }
});
