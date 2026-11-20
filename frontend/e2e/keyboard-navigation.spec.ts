import { expect, Page, test } from "@playwright/test";

/**
 * Tastatur-Workflows im echten Browser (design/KEYBOARD_ACCESSIBILITY.md, Testkonzept): nur
 * page.keyboard, keine Mausklicks. Geprüft wird, wohin der Fokus geht und ob er sichtbar ist.
 * Keine fullPage-Screenshots zwischen den Aktionen (schliessen Popups auf dem CI-Runner).
 */

async function activeInfo(page: Page) {
  return page.evaluate(() => {
    const element = document.activeElement as HTMLElement | null;
    if (!element) return null;
    const style = getComputedStyle(element);
    return {
      tag: element.tagName,
      id: element.id,
      role: element.getAttribute("role"),
      text: (element.textContent ?? "").trim().slice(0, 60),
      className: typeof element.className === "string" ? element.className : "",
      inDialog: Boolean(element.closest('[role="dialog"], [role="alertdialog"]')),
      inSidebar: Boolean(element.closest(".sidebar")),
      // sichtbarer Fokus: Outline oder Fokusring (box-shadow) bzw. Hintergrund bei Menüeinträgen
      focusVisible: style.outlineStyle !== "none" && style.outlineWidth !== "0px" ? true : style.boxShadow !== "none",
    };
  });
}

async function openTodos(page: Page) {
  await page.goto("/todos");
  await expect(page.locator("#main-content")).toBeVisible({ timeout: 60_000 });
  // Fokus an den Dokumentanfang, ohne Maus
  await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur());
}

test.describe("Tastatur: Grundlagen der App-Shell", () => {
  test("Sprunglink ist der erste Tab-Halt, sichtbar, und springt in den Hauptinhalt", async ({ page }) => {
    await openTodos(page);
    await page.keyboard.press("Tab");
    const first = await activeInfo(page);
    expect(first?.className).toContain("skip-link");
    expect(first?.focusVisible).toBe(true);
    await expect(page.locator(".skip-link")).toBeInViewport();
    await page.keyboard.press("Enter");
    expect((await activeInfo(page))?.id).toBe("main-content");
    // Der nächste Tab-Halt liegt im Inhalt, nicht in der Seitenleiste
    await page.keyboard.press("Tab");
    expect((await activeInfo(page))?.inSidebar).toBe(false);
  });

  test("«?» öffnet die Shortcut-Hilfe aus der Registry, Tab bleibt im Dialog, Escape schliesst", async ({ page }) => {
    await openTodos(page);
    await page.keyboard.press("?");
    const dialog = page.getByRole("dialog", { name: "Tastenkürzel" });
    await expect(dialog).toBeVisible();
    // Globale Kürzel plattformgerecht (Linux-Runner: Strg)
    await expect(dialog.getByText("Globale Suche öffnen oder schliessen")).toBeVisible();
    await expect(dialog.locator(".shortcut-help-kbd", { hasText: "Strg" }).first()).toBeVisible();
    for (let step = 0; step < 6; step += 1) {
      await page.keyboard.press("Tab");
      expect((await activeInfo(page))?.inDialog, `Tab ${step + 1}`).toBe(true);
    }
    await page.keyboard.press("Shift+Tab");
    expect((await activeInfo(page))?.inDialog).toBe(true);
    await page.keyboard.press("Escape");
    await expect(dialog).toBeHidden();
  });

  test("«?» löst beim Tippen in einem Feld nichts aus", async ({ page }) => {
    await openTodos(page);
    const search = page.locator(".shell-content .search-input input").first();
    test.skip((await search.count()) === 0, "Seite ohne Listensuche");
    await search.focus();
    await page.keyboard.type("a?b");
    await expect(search).toHaveValue("a?b");
    await expect(page.getByRole("dialog", { name: "Tastenkürzel" })).toHaveCount(0);
  });

  test("Strg+K öffnet die globale Suche, Escape schliesst sie und gibt den Fokus zurück", async ({ page }) => {
    await openTodos(page);
    await page.keyboard.press("Tab"); // Sprunglink
    await page.keyboard.press("Control+k");
    const combo = page.getByRole("combobox");
    await expect(combo).toBeFocused();
    await page.keyboard.press("Escape");
    await expect(combo).toHaveCount(0);
    expect((await activeInfo(page))?.className).toContain("skip-link");
  });
});

test.describe("Tastatur: Menüs und Dialoge", () => {
  test("Benutzermenü: Pfeile, Escape zurück zum Auslöser, Menüeintrag öffnet Dialog und Fokus kehrt zurück", async ({ page }) => {
    await openTodos(page);
    const trigger = page.locator(".identity-button");
    await trigger.focus();
    await page.keyboard.press("Enter");
    const menu = page.getByRole("menu");
    await expect(menu).toBeVisible();
    const first = await activeInfo(page);
    expect(first?.role).toMatch(/^menuitem/);
    expect(first?.focusVisible || (await page.evaluate(() => getComputedStyle(document.activeElement!).backgroundColor !== "rgba(0, 0, 0, 0)"))).toBe(true);
    await page.keyboard.press("ArrowDown");
    const second = await activeInfo(page);
    expect(second?.role).toMatch(/^menuitem/);
    expect(second?.text).not.toBe(first?.text);
    await page.keyboard.press("Escape");
    await expect(menu).toBeHidden();
    await expect(trigger).toBeFocused();

    // Menüeintrag «Tastenkürzel» per Pfeilen ansteuern und mit Enter öffnen
    await page.keyboard.press("Enter");
    await expect(menu).toBeVisible();
    for (let step = 0; step < 12; step += 1) {
      if ((await activeInfo(page))?.text.startsWith("Tastenkürzel")) break;
      await page.keyboard.press("ArrowDown");
    }
    expect((await activeInfo(page))?.text.startsWith("Tastenkürzel")).toBe(true);
    await page.keyboard.press("Enter");
    const dialog = page.getByRole("dialog", { name: "Tastenkürzel" });
    await expect(dialog).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(dialog).toBeHidden();
    // Der Menüeintrag existiert nicht mehr - zurück auf den Auslöser des Menüs
    await expect(trigger).toBeFocused();
  });

  test("Tab verlässt ein offenes Menü hinter dem Auslöser und schliesst es", async ({ page }) => {
    await openTodos(page);
    const trigger = page.locator(".identity-button");
    await trigger.focus();
    await page.keyboard.press("ArrowDown");
    await expect(page.getByRole("menu")).toBeVisible();
    await page.keyboard.press("Tab");
    await expect(page.getByRole("menu")).toBeHidden();
    const after = await activeInfo(page);
    expect(after?.tag).not.toBe("BODY");
  });
});

test.describe("Tastatur: ausklappbare Seitenleiste", () => {
  test("geschlossen ist die Seitenleiste kein Tab-Ziel; Menü-Knopf öffnet sie, Escape schliesst", async ({ page }) => {
    // 901-1100 px: einklappbare Seitenleiste (globals.css)
    await page.setViewportSize({ width: 1000, height: 800 });
    await openTodos(page);
    for (let step = 0; step < 12; step += 1) {
      await page.keyboard.press("Tab");
      expect((await activeInfo(page))?.inSidebar, `Tab ${step + 1} landet unsichtbar in der Seitenleiste`).toBe(false);
    }
    const toggle = page.locator(".mobile-nav-toggle");
    await expect(toggle).toHaveAttribute("aria-expanded", "false");
    await toggle.focus();
    await page.keyboard.press("Enter");
    await expect(page.locator(".sidebar")).toHaveClass(/sidebar-open/);
    await expect.poll(async () => (await activeInfo(page))?.inSidebar).toBe(true);
    await page.keyboard.press("Escape");
    await expect(page.locator(".sidebar")).not.toHaveClass(/sidebar-open/);
    await expect(toggle).toBeFocused();
  });
});

test.describe("Tastatur: Tabs", () => {
  test("Routen-Tabs: ein Tab-Halt, Pfeile verschieben den Fokus, Enter öffnet", async ({ page }) => {
    await page.goto("/");
    const tabs = page.locator('[role="tablist"].route-tabs [role="tab"]');
    await expect(page.locator("#main-content")).toBeVisible({ timeout: 60_000 });
    const count = await tabs.count();
    test.skip(count < 2, "Startseite ohne Tabs für diese Rolle");
    const tabStops = await tabs.evaluateAll((elements) => elements.filter((element) => (element as HTMLElement).tabIndex === 0).length);
    expect(tabStops).toBe(1);
    const active = page.locator('[role="tablist"].route-tabs [role="tab"][aria-selected="true"]');
    await active.focus();
    const before = page.url();
    await page.keyboard.press("ArrowRight");
    const focusedHref = await page.evaluate(() => (document.activeElement as HTMLAnchorElement | null)?.getAttribute("href"));
    expect(focusedHref).not.toBe(await active.getAttribute("href"));
    expect(page.url()).toBe(before);
    await page.keyboard.press("Enter");
    await expect(page).toHaveURL(new RegExp(`${focusedHref?.replace(/[/?]/g, "\\$&")}$`), { timeout: 60_000 });
  });
});
