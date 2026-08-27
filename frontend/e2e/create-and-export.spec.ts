import { test, expect } from "@playwright/test";

test("creates a todo and validates Markdown and PDF exports", async ({ request }) => {
  const suffix = Date.now();
  const todoResponse = await request.post("/api/todos", { data: { task: `E2E Export Todo ${suffix}` } });
  expect(todoResponse.ok(), await todoResponse.text()).toBeTruthy();
  const todo = await todoResponse.json();
  try {
    const markdown = await request.post("/api/exports/todos/markdown", { data: { filter: "all" } });
    expect(markdown.ok(), await markdown.text()).toBeTruthy();
    expect((await markdown.json()).content).toContain(`E2E Export Todo ${suffix}`);

    const templates = await (await request.get("/api/templates")).json();
    expect(templates.length).toBeGreaterThan(0);
    const pdf = await request.post("/api/exports/todos", { data: { template_id: templates[0].id, filter: "all" }, timeout: 40_000 });
    expect(pdf.ok(), await pdf.text()).toBeTruthy();
    const metadata = await pdf.json();
    const download = await request.get(metadata.content_url);
    expect(download.ok()).toBeTruthy();
    expect((await download.body()).subarray(0, 5).toString()).toBe("%PDF-");
  } finally {
    await request.delete(`/api/protocol-todos/${todo.id}`);
  }
});
