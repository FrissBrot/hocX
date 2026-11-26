import { expect, type Page } from "@playwright/test";

// Screenshots der Cloud-Import-Specs hell/dunkel bei 1440 und 390 px.
//
// 390 px läuft bewusst in einer zweiten Seite derselben Sitzung: ein Größenwechsel der
// Hauptseite schaltet AppShell zwischen Desktop- und Mobil-Shell um, der Wizard würde neu
// gemountet und verlöre Formulareingaben und den aufgeklappten Ordnerbaum mitten im Test.
// Die zweite Seite zeigt den Stand des Auftrags auf dem Server (?job=<id>).
// Seiten ohne App-Shell (Google-Picker-Origin) behalten ihren Zustand beim Größenwechsel: dort
// `inPlace`, denn eine zweite Seite hätte kein (einmaliges) Ticket mehr.
export async function shootCloud(page: Page, dir: string, name: string, options: { inPlace?: boolean } = {}) {
  for (const theme of ["light", "dark"] as const) {
    await page.evaluate((value) => document.documentElement.setAttribute("data-theme", value), theme);
    await page.waitForTimeout(150);
    await page.screenshot({ path: `test-results/${dir}/${name}-${theme}-1440.png`, fullPage: true });
  }
  await page.evaluate(() => document.documentElement.setAttribute("data-theme", "light"));

  if (options.inPlace) {
    for (const theme of ["light", "dark"] as const) {
      await page.evaluate((value) => document.documentElement.setAttribute("data-theme", value), theme);
      await page.setViewportSize({ width: 390, height: 844 });
      await page.waitForTimeout(150);
      await page.screenshot({ path: `test-results/${dir}/${name}-${theme}-390.png`, fullPage: true });
      expect.soft(await page.evaluate(() => document.documentElement.scrollWidth), `${name} ${theme}: Seitenbreite bei 390 px`).toBeLessThanOrEqual(390);
    }
    await page.evaluate(() => document.documentElement.setAttribute("data-theme", "light"));
    await page.setViewportSize({ width: 1440, height: 900 });
    return;
  }

  const url = new URL(page.url());
  if (url.pathname === "/files/import" && !url.searchParams.get("job")) {
    const jobs = (await (await page.request.get("/api/cloud-import/jobs")).json()) as { id: string }[];
    if (jobs[0]) url.searchParams.set("job", jobs[0].id);
  }
  const narrow = await page.context().newPage();
  try {
    await narrow.setViewportSize({ width: 390, height: 844 });
    await narrow.goto(url.pathname + url.search);
    await narrow.waitForLoadState("networkidle");
    for (const theme of ["light", "dark"] as const) {
      await narrow.evaluate((value) => document.documentElement.setAttribute("data-theme", value), theme);
      await narrow.waitForTimeout(150);
      await narrow.screenshot({ path: `test-results/${dir}/${name}-${theme}-390.png`, fullPage: true });
      // Smartphone: die Seite wird nie breiter als der Viewport (Vorbild admin-console.spec.ts)
      const overflow = await narrow.evaluate(() => ({
        width: document.documentElement.scrollWidth,
        // die äussersten Elemente, die über den Viewport ragen (für die Fehlermeldung)
        wide: Array.from(document.querySelectorAll<HTMLElement>("body *"))
          .filter((el) => el.getBoundingClientRect().right > window.innerWidth + 1)
          .filter((el) => !el.parentElement || el.parentElement.getBoundingClientRect().right <= window.innerWidth + 1)
          .slice(0, 5)
          .map((el) => `${el.tagName.toLowerCase()}.${el.className}`),
      }));
      expect.soft(overflow.width, `${name} ${theme}: Seitenbreite bei 390 px (${overflow.wide.join(", ")})`).toBeLessThanOrEqual(390);
    }
  } finally {
    await narrow.close();
  }
}
