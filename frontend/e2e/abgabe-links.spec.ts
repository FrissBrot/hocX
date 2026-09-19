import { test, expect, request as playwrightRequest, APIRequestContext } from "@playwright/test";
import { authFiles } from "./auth";

// Abgabe-Links: the public Abgabebox is reached via a random link token, never via the tenant
// slug. These cases run against the real stack (main backend + abgabebox-backend under the
// restricted hocx_abgabebox role + both frontends). Documented as LNK-01..LNK-08 in
// docs-site/docs/technik/abgabe-links-testbook.md.

type Link = { id: string; name: string; is_default: boolean; token: string; url: string; assignment_count: number };
type Assignment = { id: string; public_slug: string; link_ids: string[] };

const suffix = `${Date.now()}`;

async function createEventAndAbgabe(api: APIRequestContext, name: string, linkIds?: string[]) {
  const tag = `e2e-links-${name}-${suffix}`;
  const event = await api.post("/api/events", {
    data: { event_date: new Date().toISOString().slice(0, 10), title: `E2E Links Termin ${name} ${suffix}`, tag },
  });
  expect(event.ok(), await event.text()).toBeTruthy();
  const slug = `e2e-links-${name}-${suffix}`;
  const assignment = await api.post("/api/submission-assignments", {
    data: {
      title: `E2E Links Abgabe ${name} ${suffix}`,
      public_slug: slug,
      source_type: "events",
      tag_filter: tag,
      offset_days_before: 30,
      offset_days_after: 30,
      allowed_file_types: ["jpg", "png"],
      max_files_per_element: 3,
      max_file_size_mb: 5,
      sort_order: "date",
      ...(linkIds === undefined ? {} : { link_ids: linkIds }),
    },
  });
  expect(assignment.ok(), await assignment.text()).toBeTruthy();
  return { eventId: (await event.json()).id as string, assignment: (await assignment.json()) as Assignment };
}

async function createLink(api: APIRequestContext, name: string, isDefault = false): Promise<Link> {
  const response = await api.post("/api/submission-links", { data: { name: `${name} ${suffix}`, is_default: isDefault } });
  expect(response.ok(), await response.text()).toBeTruthy();
  return response.json();
}

async function listLinks(api: APIRequestContext): Promise<Link[]> {
  const response = await api.get("/api/submission-links");
  expect(response.ok(), await response.text()).toBeTruthy();
  return response.json();
}

test.describe("Abgabe-Links", () => {
  test.describe.configure({ mode: "serial" });

  let api: APIRequestContext;
  let publicApi: APIRequestContext;
  let originalDefaultId: string | undefined;
  const createdLinkIds: string[] = [];
  const createdAssignmentIds: string[] = [];
  const createdEventIds: string[] = [];

  test.beforeAll(async () => {
    api = await playwrightRequest.newContext({ baseURL: process.env.PLAYWRIGHT_BASE_URL, storageState: authFiles.admin });
    // Fresh, cookie-less context against the separate Abgabebox origin.
    publicApi = await playwrightRequest.newContext({ baseURL: process.env.E2E_ABGABEBOX_BASE_URL });
    originalDefaultId = (await listLinks(api)).find((link) => link.is_default)?.id;
  });

  test.afterAll(async () => {
    for (const id of createdAssignmentIds) await api.delete(`/api/submission-assignments/${id}`).catch(() => {});
    for (const id of createdEventIds) await api.delete(`/api/events/${id}`).catch(() => {});
    for (const id of createdLinkIds) await api.delete(`/api/submission-links/${id}`).catch(() => {});
    // Leave the tenant's default link as we found it.
    if (originalDefaultId) await api.patch(`/api/submission-links/${originalDefaultId}`, { data: { is_default: true } }).catch(() => {});
    await api.dispose();
    await publicApi.dispose();
  });

  const elementsUrl = (token: string, slug: string) => `/api/public/${token}/assignments/${slug}/elements`;

  test("LNK-01 tenant has exactly one default link with a long random token and a token URL", async () => {
    const links = await listLinks(api);
    const defaults = links.filter((link) => link.is_default);
    expect(defaults).toHaveLength(1);
    expect(defaults[0].token.length).toBeGreaterThanOrEqual(32);
    expect(defaults[0].token).toMatch(/^[A-Za-z0-9_-]+$/);
    expect(defaults[0].url.endsWith(`/${defaults[0].token}`)).toBeTruthy();
    expect(new Set(links.map((link) => link.token)).size).toBe(links.length);
  });

  test("LNK-02 links have unique clear names; renaming and switching the default keep a single default", async () => {
    const first = await createLink(api, "Eltern");
    createdLinkIds.push(first.id);
    const duplicate = await api.post("/api/submission-links", { data: { name: first.name.toUpperCase() } });
    expect(duplicate.status()).toBe(400);

    const renamed = await api.patch(`/api/submission-links/${first.id}`, { data: { name: `Leiterteam ${suffix}` } });
    expect(renamed.ok(), await renamed.text()).toBeTruthy();
    expect((await renamed.json()).token).toBe(first.token); // renaming never changes the credential

    const promoted = await api.patch(`/api/submission-links/${first.id}`, { data: { is_default: true } });
    expect(promoted.ok(), await promoted.text()).toBeTruthy();
    const defaults = (await listLinks(api)).filter((link) => link.is_default);
    expect(defaults.map((link) => link.id)).toEqual([first.id]);
  });

  test("LNK-03 a new Abgabe defaults to the default link; an explicit selection and 'none' are respected", async () => {
    const links = await listLinks(api);
    const defaultLink = links.find((link) => link.is_default)!;
    const other = await createLink(api, "Andere");
    createdLinkIds.push(other.id);

    const implicit = await createEventAndAbgabe(api, "implicit");
    const chosen = await createEventAndAbgabe(api, "chosen", [other.id]);
    const none = await createEventAndAbgabe(api, "none", []);
    for (const created of [implicit, chosen, none]) {
      createdAssignmentIds.push(created.assignment.id);
      createdEventIds.push(created.eventId);
    }

    expect(implicit.assignment.link_ids).toEqual([defaultLink.id]);
    expect(chosen.assignment.link_ids).toEqual([other.id]);
    expect(none.assignment.link_ids).toEqual([]);
  });

  test("LNK-04 a link only reaches the Abgaben attached to it; unknown tokens and the tenant slug give 404", async () => {
    const linkA = await createLink(api, "A");
    const linkB = await createLink(api, "B");
    createdLinkIds.push(linkA.id, linkB.id);
    const { eventId, assignment } = await createEventAndAbgabe(api, "scoped", [linkA.id]);
    createdEventIds.push(eventId);
    createdAssignmentIds.push(assignment.id);

    const viaA = await publicApi.get(elementsUrl(linkA.token, assignment.public_slug));
    expect(viaA.status()).toBe(200);
    expect((await viaA.json()).length).toBeGreaterThan(0);

    // Link B is valid but the Abgabe is not attached to it - indistinguishable from "not there".
    const viaB = await publicApi.get(elementsUrl(linkB.token, assignment.public_slug));
    expect(viaB.status()).toBe(404);
    expect((await publicApi.get(`/api/public/${linkB.token}/assignments`)).status()).toBe(200);

    expect((await publicApi.get(elementsUrl("x".repeat(32), assignment.public_slug))).status()).toBe(404);
    expect((await publicApi.get(elementsUrl("kurz", assignment.public_slug))).status()).toBe(404);

    // The tenant's public_slug is no longer an access credential.
    const session = await (await api.get("/api/auth/session")).json();
    const tenantSlug = (session.current_tenant.public_slug as string | null) ?? `e2e-links-${suffix}`;
    if (!session.current_tenant.public_slug) {
      await api.patch(`/api/tenants/${session.current_tenant.id}`, { multipart: { public_slug: tenantSlug } });
    }
    expect((await publicApi.get(elementsUrl(tenantSlug, assignment.public_slug))).status()).toBe(404);
  });

  test("LNK-05 one Abgabe can be reached over several links at once", async () => {
    const linkA = await createLink(api, "Mehrfach A");
    const linkB = await createLink(api, "Mehrfach B");
    createdLinkIds.push(linkA.id, linkB.id);
    const { eventId, assignment } = await createEventAndAbgabe(api, "multi", [linkA.id, linkB.id]);
    createdEventIds.push(eventId);
    createdAssignmentIds.push(assignment.id);

    for (const link of [linkA, linkB]) {
      expect((await publicApi.get(elementsUrl(link.token, assignment.public_slug))).status()).toBe(200);
    }

    // Take it off link A via the configurator's link selection - link B keeps working.
    const patched = await api.patch(`/api/submission-assignments/${assignment.id}`, { data: { link_ids: [linkB.id] } });
    expect(patched.ok(), await patched.text()).toBeTruthy();
    expect((await patched.json()).link_ids).toEqual([linkB.id]);
    expect((await publicApi.get(elementsUrl(linkA.token, assignment.public_slug))).status()).toBe(404);
    expect((await publicApi.get(elementsUrl(linkB.token, assignment.public_slug))).status()).toBe(200);
  });

  test("LNK-06 a new key invalidates the old URL immediately; deleting a link cuts access", async () => {
    const link = await createLink(api, "Widerruf");
    createdLinkIds.push(link.id);
    const { eventId, assignment } = await createEventAndAbgabe(api, "revoke", [link.id]);
    createdEventIds.push(eventId);
    createdAssignmentIds.push(assignment.id);
    expect((await publicApi.get(elementsUrl(link.token, assignment.public_slug))).status()).toBe(200);

    const regenerated = await api.post(`/api/submission-links/${link.id}/regenerate`);
    expect(regenerated.ok(), await regenerated.text()).toBeTruthy();
    const fresh = (await regenerated.json()) as Link;
    expect(fresh.id).toBe(link.id);
    expect(fresh.token).not.toBe(link.token);
    expect((await publicApi.get(elementsUrl(link.token, assignment.public_slug))).status()).toBe(404);
    expect((await publicApi.get(elementsUrl(fresh.token, assignment.public_slug))).status()).toBe(200);

    const deleted = await api.delete(`/api/submission-links/${link.id}`);
    expect(deleted.ok(), await deleted.text()).toBeTruthy();
    expect((await publicApi.get(elementsUrl(fresh.token, assignment.public_slug))).status()).toBe(404);
    const reloaded = (await (await api.get("/api/submission-assignments")).json()) as Assignment[];
    expect(reloaded.find((item) => item.id === assignment.id)?.link_ids).toEqual([]);
  });

  test("LNK-07 links (and their tokens) are not accessible to another workspace's reader", async () => {
    // authFiles.tenantTwo is the admin's session in its second workspace, where the seeded role
    // is "reader" (see roles-and-tenants.spec.ts): link management is writer-only, so every
    // call - including listing, which would expose the tokens - is refused with 403. The
    // cross-tenant id scoping itself (foreign link ids resolve to nothing) is covered at
    // service level by backend/tests/test_submission_links.py.
    const link = await createLink(api, "Fremd");
    createdLinkIds.push(link.id);
    const other = await playwrightRequest.newContext({ baseURL: process.env.PLAYWRIGHT_BASE_URL, storageState: authFiles.tenantTwo });
    try {
      expect((await other.get("/api/submission-links")).status()).toBe(403);
      expect((await other.post("/api/submission-links", { data: { name: `Einbruch ${suffix}` } })).status()).toBe(403);
      expect((await other.patch(`/api/submission-links/${link.id}`, { data: { name: "gekapert" } })).status()).toBe(403);
      expect((await other.post(`/api/submission-links/${link.id}/regenerate`)).status()).toBe(403);
      expect((await other.delete(`/api/submission-links/${link.id}`)).status()).toBe(403);
    } finally {
      await other.dispose();
    }
    const untouched = (await listLinks(api)).find((item) => item.id === link.id);
    expect(untouched?.name).toContain("Fremd");
    expect(untouched?.token).toBe(link.token);
  });

  test("LNK-08 browser: admin sees the links in the Links dialog; the public page works only with the token", async ({ page, browser }) => {
    const link = await createLink(api, "Browser");
    createdLinkIds.push(link.id);
    const { eventId, assignment } = await createEventAndAbgabe(api, "browser", [link.id]);
    createdEventIds.push(eventId);
    createdAssignmentIds.push(assignment.id);

    await page.goto("/submission-assignments");
    await page.getByRole("button", { name: /^Links \(\d+\)$/ }).click();
    await expect(page.getByText(link.name, { exact: true })).toBeVisible();
    await expect(page.getByText(link.url, { exact: true })).toBeVisible();

    const publicContext = await browser.newContext({ baseURL: process.env.E2E_ABGABEBOX_BASE_URL, storageState: undefined });
    try {
      const publicPage = await publicContext.newPage();
      await publicPage.goto(`/${link.token}`);
      await expect(publicPage.getByText(`E2E Links Abgabe browser ${suffix}`)).toBeVisible();

      const wrong = await publicPage.goto(`/${"y".repeat(32)}`);
      expect(wrong?.status()).toBe(404);
      // Checked on the server-rendered body, not via visibility: the dev abgabebox-frontend's
      // client hydration is unreliable in this stack (see abgabebox-photo-album-sync.spec.ts).
      expect(await wrong?.text()).toContain("Nicht gefunden");

      const root = await publicPage.goto("/");
      expect(root?.status()).toBe(200);
      expect(await root?.text()).toContain("Abgabe-Link verwenden");
      const headers = (await root?.allHeaders()) ?? {};
      expect(headers["referrer-policy"]).toBe("no-referrer");
      expect(headers["x-robots-tag"]).toContain("noindex");
    } finally {
      await publicContext.close();
    }
  });
});
