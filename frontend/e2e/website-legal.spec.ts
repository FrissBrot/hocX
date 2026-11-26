import { expect, test } from "@playwright/test";

// Rechtstexte der Website (Datenschutzerklärung, Nutzungsbedingungen): ohne Sitzung erreichbar,
// Inhaltsverzeichnis mit Ankern, gegenseitig verlinkt, auf 390 px ohne horizontales Scrollen.
// Im E2E-Stack gibt es keine Website-Domain (TRAEFIK_WEBSITE_DOMAIN), deshalb direkt über
// /website/<seite>; auf der Website-Domain schreibt proxy.ts /<seite> genau dorthin um.
// Screenshots (Light/Dark, 1440 und 390 px) landen in test-results/website-legal-*.png.

test.use({ storageState: { cookies: [], origins: [] } });

const PAGES = [
  { path: "/website/privacy", title: "Datenschutzerklärung", other: "/website/terms", firstAnchor: "controller" },
  { path: "/website/terms", title: "Nutzungsbedingungen", other: "/website/privacy", firstAnchor: "scope" },
];

for (const legal of PAGES) {
  test(`Website: ${legal.title} ohne Anmeldung, mit Ankern und 390 px`, async ({ page }) => {
    test.setTimeout(120_000);
    const response = await page.goto(legal.path);
    expect(response?.status()).toBe(200);
    expect(new URL(page.url()).pathname).toBe(legal.path);
    await expect(page.getByRole("heading", { level: 1, name: legal.title })).toBeVisible();
    await expect(page.getByText(/MISSING_MESSAGE|legal\.(privacy|terms)\./)).toHaveCount(0);

    // Inhaltsverzeichnis: jeder Eintrag zeigt auf einen vorhandenen Abschnitt
    const toc = page.getByRole("navigation", { name: "Inhalt" });
    const hrefs = await toc.getByRole("link").evaluateAll((links) => links.map((link) => link.getAttribute("href")));
    expect(hrefs.length).toBeGreaterThan(5);
    expect(hrefs[0]).toBe(`#${legal.firstAnchor}`);
    for (const href of hrefs) await expect(page.locator(`section${href}`)).toHaveCount(1);

    // Tastatur: Anker per Enter anspringen
    await toc.getByRole("link").nth(1).focus();
    await page.keyboard.press("Enter");
    await expect(page).toHaveURL(new RegExp(`${hrefs[1]}$`));
    await expect(page.locator(`section${hrefs[1]}`)).toBeInViewport();

    // Gegenseitige Verlinkung in der Fusszeile
    await expect(page.locator("footer").locator(`a[href="${legal.other}"]`)).toHaveCount(1);

    for (const theme of ["light", "dark"]) {
      for (const width of [1440, 390]) {
        await page.setViewportSize({ width, height: 900 });
        await page.goto(legal.path);
        await page.evaluate((value) => localStorage.setItem("hocx-theme", value), theme);
        await page.reload();
        await expect(page.getByRole("heading", { level: 1, name: legal.title })).toBeVisible();
        await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
        const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
        expect(overflow, `${legal.path} ${theme} ${width}px scrollt horizontal`).toBeLessThanOrEqual(0);
        const name = legal.path.split("/").pop();
        await page.screenshot({ path: `test-results/website-legal-${name}-${theme}-${width}.png` });
        await page.screenshot({ path: `test-results/website-legal-${name}-${theme}-${width}-full.png`, fullPage: true });
      }
    }
  });
}

test("Website: Startseite verlinkt beide Rechtstexte", async ({ page }) => {
  await page.goto("/website");
  const footer = page.locator("footer");
  await expect(footer.getByRole("link", { name: "Datenschutzerklärung" })).toHaveAttribute("href", "/website/privacy");
  await expect(footer.getByRole("link", { name: "Nutzungsbedingungen" })).toHaveAttribute("href", "/website/terms");
});
