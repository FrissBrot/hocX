import { expect, type Page } from "@playwright/test";

/**
 * Protokoll öffnen wie eine Person, die nicht am linken Rand steht: Playwright beginnt mit dem
 * Mauszeiger bei (0,0) - in der Schreibansicht ist das der Rand, der beim Überfahren das Menü
 * öffnet (sidebar-edge-trigger). Danach Mauszeiger in die Mitte und ein so geöffnetes Menü
 * schliessen, sonst verdeckt dessen Hintergrund Gliederung und Dock.
 */
export async function openProtocol(page: Page, protocolId: string) {
  await page.goto(`/protocols/${protocolId}`);
  await expect(page.locator(".protocol-doc-section").first()).toBeVisible();
  await page.mouse.move(Math.round((page.viewportSize()?.width ?? 1440) / 2), 400);
  const overlay = page.locator(".sidebar-overlay");
  if (await overlay.isVisible()) await overlay.click({ position: { x: (page.viewportSize()?.width ?? 1440) - 40, y: 400 } });
  await expect(overlay).toHaveCount(0);
}
