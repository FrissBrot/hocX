import { expect, type APIRequestContext } from "@playwright/test";

// PDF-Export als Auftrag (Migration 0150): POST /api/documents/render antwortet mit 202 und einer
// Auftrags-ID, der job-worker rendert. Hier wird abgefragt, bis der Auftrag fertig ist, und der
// registrierte Export zurückgegeben (short_id, verify_url, content_url …).
export async function renderPdf(
  request: APIRequestContext,
  data: Record<string, unknown>,
  { timeoutMs = 90_000 }: { timeoutMs?: number } = {},
) {
  const response = await request.post("/api/documents/render", { data });
  expect(response.status(), await response.text()).toBe(202);
  let job = await response.json();
  const deadline = Date.now() + timeoutMs;
  while (job.status === "queued" || job.status === "running") {
    expect(Date.now(), `PDF-Auftrag ${job.id} nicht rechtzeitig fertig (Status ${job.status})`).toBeLessThan(deadline);
    await new Promise((resolve) => setTimeout(resolve, 1000));
    const poll = await request.get(`/api/documents/render-jobs/${job.id}`);
    expect(poll.ok(), await poll.text()).toBeTruthy();
    job = await poll.json();
  }
  expect(job.status, JSON.stringify(job.error)).toBe("done");
  return job.export;
}
