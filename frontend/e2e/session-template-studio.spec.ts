import { test, expect } from "@playwright/test";

// Kopien anderer, parallel laufender Tests nie als Ausgangspunkt nehmen: eine kopierte
// Sitzungsvorlage übernimmt deren Gestaltungs-Zuweisung, die Gestaltung wäre dann geteilt.
function sourceTemplate(templates: { id: string; name: string }[]) {
  return templates.find((item) => !item.name.startsWith("E2E")) ?? templates[0];
}

// Vorlagen-Editor einer Sitzungsvorlage: Traktanden mit ihren Bausteinen, Schalter direkt am
// Baustein, Ansichten Protokoll-Editor / PDF. Arbeitet auf einer Kopie der Demo-Vorlage und legt
// Screenshots (Light/Dark, 1440 px) ab.

test("Vorlagen-Editor: Baustein einstellen und PDF der Vorlage ansehen", async ({ page }) => {
  test.setTimeout(180_000);
  const templates = await (await page.request.get("/api/templates")).json();
  const copy = await (await page.request.post(`/api/templates/${sourceTemplate(templates).id}/duplicate`, { data: { name: `E2E Studio ${Date.now()}` } })).json();
  try {
    for (const theme of ["light", "dark"]) {
      await page.setViewportSize({ width: 1440, height: 1000 });
      await page.goto(`/templates/${copy.id}`);
      await page.evaluate((value) => localStorage.setItem("hocx-theme", value), theme);
      await page.reload();
      const editor = page.getByRole("region", { name: "Traktanden" });
      await expect(editor).toBeVisible({ timeout: 60_000 });
      const firstBlock = editor.locator(".session-studio-block").first();
      await firstBlock.click();
      const properties = page.getByRole("complementary", { name: "Eigenschaften" });
      await expect(properties.getByRole("switch", { name: /Im PDF zeigen/ })).toBeVisible();
      await page.screenshot({ path: `test-results/session-studio-editor-${theme}-1440.png` });
    }

    // Im PDF ausblenden: Hinweis am Baustein, gespeichert je Vorlage
    const properties = page.getByRole("complementary", { name: "Eigenschaften" });
    const pdfSwitch = properties.getByRole("switch", { name: /Im PDF zeigen/ });
    const saved = page.waitForResponse((response) => response.url().includes("/behavior") && response.request().method() === "PATCH");
    await pdfSwitch.click();
    expect((await saved).ok()).toBeTruthy();
    await expect(page.getByRole("region", { name: "Traktanden" }).getByText("Nicht im PDF").first()).toBeVisible();

    await page.getByRole("tab", { name: /^PDF/ }).click();
    await expect(page.getByRole("img", { name: "Seite 1" }).first()).toBeVisible({ timeout: 90_000 });
    await page.screenshot({ path: "test-results/session-studio-pdf-dark-1440.png" });

    // Zuweisungs-Leiste: verwendete Gestaltung, wer sie sonst nutzt, «Nur hier anpassen» erstellt
    // eine Kopie und sagt, dass Änderungen an der Ausgangsgestaltung hier nicht mehr gelten
    const bar = page.getByRole("region", { name: "Gestaltung des Protokolls" });
    await expect(bar.getByText("Das Protokoll-PDF verwendet die Gestaltung")).toBeVisible();
    await bar.getByRole("button", { name: /Nur hier anpassen/ }).click();
    await expect(bar.getByText(/gelten für diese Vorlage nicht mehr/)).toBeVisible({ timeout: 30_000 });
    await expect(bar.getByText("Nur in dieser Vorlage verwendet.")).toBeVisible();
    for (const theme of ["dark", "light"]) {
      await page.evaluate((value) => localStorage.setItem("hocx-theme", value), theme);
      await page.evaluate((value) => document.documentElement.setAttribute("data-theme", value), theme);
      await bar.screenshot({ path: `test-results/session-studio-design-bar-${theme}-1440.png` });
    }
  } finally {
    await page.request.delete(`/api/templates/${copy.id}`);
  }
});
