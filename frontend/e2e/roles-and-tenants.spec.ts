import { test, expect, request as playwrightRequest } from "@playwright/test";
import { authFiles } from "./auth";

test("writer may create content but cannot administer users", async () => {
  const api = await playwrightRequest.newContext({ baseURL: process.env.PLAYWRIGHT_BASE_URL, storageState: authFiles.writer });
  const todo = await api.post("/api/todos", { data: { task: `Writer E2E ${Date.now()}` } });
  expect(todo.status()).toBe(201);
  const todoData = await todo.json();
  expect((await api.get("/api/users")).status()).toBe(403);
  await api.delete(`/api/protocol-todos/${todoData.id}`);
  await api.dispose();
});

test("reader has read-only access", async () => {
  const api = await playwrightRequest.newContext({ baseURL: process.env.PLAYWRIGHT_BASE_URL, storageState: authFiles.reader });
  expect((await api.get("/api/todos")).ok()).toBeTruthy();
  expect((await api.post("/api/todos", { data: { task: "Forbidden reader todo" } })).status()).toBe(403);
  expect((await api.post("/api/events", { data: { event_date: "2026-08-26", title: "Forbidden reader event" } })).status()).toBe(403);
  await api.dispose();
});

test("tenant data cannot be read or changed from another workspace", async ({ request }) => {
  const created = await request.post("/api/todos", { data: { task: `Tenant boundary ${Date.now()}` } });
  expect(created.ok()).toBeTruthy();
  const todo = await created.json();
  const other = await playwrightRequest.newContext({ baseURL: process.env.PLAYWRIGHT_BASE_URL, storageState: authFiles.tenantTwo });
  const items = await (await other.get("/api/todos")).json();
  expect(items.some((item: { id: string }) => item.id === todo.id)).toBeFalsy();
  // authFiles.tenantTwo is admin@hocx.local's session in its *second* tenant, where the
  // seeded membership is "reader" - patch_todo's require_writer(user) check runs before
  // any tenant-ownership lookup, so an insufficient role there means 403, not 404. The
  // GET above already covers the tenant-boundary case (the cross-tenant todo genuinely
  // isn't in the list); this only additionally confirms cross-tenant + insufficient role
  // can't mutate it either.
  expect((await other.patch(`/api/protocol-todos/${todo.id}`, { data: { task: "cross tenant" } })).status()).toBe(403);
  await other.dispose();
  await request.delete(`/api/protocol-todos/${todo.id}`);
});
