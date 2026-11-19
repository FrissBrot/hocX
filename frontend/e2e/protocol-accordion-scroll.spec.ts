import { expect, test, type APIRequestContext } from "@playwright/test";

// Akkordeon an die Scrollposition gekoppelt (accordion-scroll.ts): scrollt ein Protokoll mit
// Punkten unterschiedlicher Länge in Mausrad-Schritten. Ein Textblock in der Mitte muss genau um
// den Scrollweg mitlaufen (kein Sprung beim Auf-/Zuklappen der Nachbarn), Sprünge über die
// Schnellnavigation landen offen im Bild. Screenshots unter test-results/accordion/.

async function json(request: APIRequestContext, path: string, data: unknown) {
  const response = await request.post(path, { data });
  expect(response.ok(), `POST ${path}: ${await response.text()}`).toBeTruthy();
  return response.json();
}

test("Akkordeon scrollt ohne Sprung", async ({ request, page }) => {
  test.setTimeout(300_000);
  const suffix = Date.now();
  const template = await json(request, "/api/templates", { name: `E2E Scroll ${suffix}`, protocol_number_pattern: "S-{n}", title_pattern: "Scroll {dd.mm.yyyy}", auto_create_next_protocol: false });
  const sizes = [1, 4, 1, 6, 2, 1, 5, 1];
  for (const [index, count] of sizes.entries()) {
    const definition = await json(request, "/api/element-definitions", {
      title: `Punkt ${index + 1} (${count})`,
      blocks: Array.from({ length: count }, (_, block) => ({ id: block + 1, title: `Text ${block + 1}`, element_type_id: 1, render_type_id: 2, sort_index: (block + 1) * 10, configuration_json: {} })),
    });
    await json(request, `/api/templates/${template.id}/elements`, { element_definition_id: definition.id, sort_index: (index + 1) * 10 });
  }
  const protocol = await json(request, "/api/protocols/from-template", { template_id: template.id, protocol_date: new Date().toISOString().slice(0, 10), title: `E2E Scroll ${suffix}` });

  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(`/protocols/${protocol.id}`);
  const doc = page.locator(".protocol-document");
  await expect(doc.locator(".protocol-doc-section").first()).toBeVisible();
  await page.waitForTimeout(1500);
  const box = (await doc.boundingBox())!;
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);

  const sample = () => page.evaluate(() => {
    const root = document.querySelector<HTMLElement>(".protocol-document")!;
    const rect = root.getBoundingClientRect();
    const x = rect.left + rect.width / 2;
    const y = rect.top + rect.height / 2;
    const hit = document.elementFromPoint(x, y) as HTMLElement | null;
    // Nur Inhalt (Textblöcke): Kopf und Rahmen eines zuklappenden Punkts gleiten bewusst
    const card = hit?.closest<HTMLElement>(".editor-block-card") ?? null;
    if (card && !card.dataset.probe) card.dataset.probe = String(Math.random());
    const open = Array.from(document.querySelectorAll<HTMLElement>(".protocol-doc-section")).map((s) => Number(getComputedStyle(s).getPropertyValue("--open") || 0).toFixed(2));
    return { probe: card?.dataset.probe ?? null, top: card?.getBoundingClientRect().top ?? null, scrollTop: root.scrollTop, open };
  });
  const topOf = (probe: string) => page.evaluate((p) => document.querySelector<HTMLElement>(`[data-probe="${p}"]`)?.getBoundingClientRect().top ?? null, probe);

  const results: { dir: string; moved: number; scrolled: number; open: string }[] = [];
  for (const dir of ["down", "up"] as const) {
    for (let step = 0; step < 45; step += 1) {
      const before = await sample();
      await page.mouse.wheel(0, dir === "down" ? 80 : -80);
      await page.waitForTimeout(220);
      const after = await sample();
      if (before.probe && before.top !== null) {
        const top = await topOf(before.probe);
        if (top !== null) results.push({ dir, moved: before.top - top, scrolled: (after.scrollTop - before.scrollTop) * 0.84, open: after.open.join(" ") });
      }
      if (step % 10 === 5) await page.screenshot({ path: `test-results/accordion/${dir}-${step}.png` });
    }
  }
  // Sprung über die Schnellnavigation: Ziel landet offen im Bild
  for (const target of ["Punkt 7 (5)", "Punkt 2 (4)", "Punkt 8 (1)"]) {
    await page.locator(".protocol-quicknav").getByText(target, { exact: true }).click();
    await page.waitForTimeout(1500);
    const state = await page.evaluate((title) => {
      const root = document.querySelector<HTMLElement>(".protocol-document")!;
      const section = Array.from(document.querySelectorAll<HTMLElement>(".protocol-doc-section")).find((s) => s.querySelector("h2")?.textContent === title)!;
      const r = section.getBoundingClientRect();
      const box = root.getBoundingClientRect();
      return { open: getComputedStyle(section).getPropertyValue("--open"), active: section.classList.contains("protocol-doc-section-active"), top: r.top - box.top, bottom: r.bottom - box.top, height: box.height };
    }, target);
    console.log(`JUMP ${target} ${JSON.stringify(state)}`);
    expect(state.active).toBe(true);
    expect(Number(state.open)).toBe(1);
    expect(state.top).toBeGreaterThanOrEqual(-2);
    expect(state.top).toBeLessThan(state.height / 2);
    await page.screenshot({ path: `test-results/accordion/jump-${target.replace(/\W+/g, "")}.png` });
  }
  // Mausrad 80 px; die Dokumentansicht ist auf 84 % gezoomt (protocol.css), am Rand des
  // Scrollbereichs bewegt sich weniger
  const off = results.filter((r) => Math.abs(r.scrolled) > 1 && Math.abs(Math.abs(r.moved) - Math.abs(r.scrolled)) > 6);
  expect(results.length).toBeGreaterThan(40);
  expect(off, JSON.stringify(off)).toEqual([]);
  await request.delete(`/api/protocols/${protocol.id}`);
});
