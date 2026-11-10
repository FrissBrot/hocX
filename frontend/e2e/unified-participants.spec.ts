import { expect, test } from "@playwright/test";

test("Teilnehmer behalten beim Aktivieren und Deaktivieren des Logins ihre Identität", async ({ request, page }) => {
  const name = `Identität ${Date.now()}`;
  const response = await request.post("/api/participants", { data: { display_name: name } });
  expect(response.ok(), await response.text()).toBeTruthy();
  const participant = await response.json();
  try {
    expect(participant.email).toBeNull();
    expect(participant.login_enabled).toBe(false);
    const users = await (await request.get("/api/users")).json();
    expect(users.find((user: { id: string }) => user.id === participant.id)).toBeTruthy();
    await page.goto("/participants");
    await page.getByText(name, { exact: true }).click();
    const dialog = page.getByRole("dialog");
    await dialog.getByLabel("Login aktivieren", { exact: true }).check();
    await dialog.getByLabel("E-Mail", { exact: true }).fill(`identity-${Date.now()}@example.invalid`);
    await dialog.getByLabel(/^Neues Passwort/).fill("Secure-Participant-Password-123!");
    await dialog.getByRole("button", { name: "Teilnehmer speichern", exact: true }).click();
    await expect(dialog).not.toBeVisible();
    await page.getByRole("tab", { name: /Teilnehmer mit Login/ }).click();
    await expect(page.getByText(name, { exact: true })).toBeVisible();
    const updatedUsers = await (await request.get("/api/users")).json();
    expect(updatedUsers.find((user: { id: string }) => user.id === participant.id).login_enabled).toBe(true);
    await page.getByText(name, { exact: true }).click();
    await dialog.getByLabel("Login aktivieren", { exact: true }).uncheck();
    await dialog.getByRole("button", { name: "Teilnehmer speichern", exact: true }).click();
    await expect(dialog).not.toBeVisible();
    await page.getByRole("tab", { name: /^Teilnehmer(?:\s*\d+)?$/ }).click();
    await expect(page.getByText(name, { exact: true })).toBeVisible();
  } finally {
    await request.delete(`/api/participants/${participant.id}`);
  }
});

for (const width of [1440, 390]) {
  for (const theme of ["light", "dark"]) {
    test(`Teilnehmeransichten ${width}px ${theme}`, async ({ page }) => {
      await page.setViewportSize({ width, height: 1000 });
      await page.addInitScript((value) => localStorage.setItem("hocx-theme", value), theme);
      await page.goto("/participants");
      await page.evaluate((value) => document.documentElement.setAttribute("data-theme", value), theme);
      const loginTab = width === 390 ? page.getByRole("button", { name: /Teilnehmer mit Login/ }) : page.getByRole("tab", { name: /Teilnehmer mit Login/ });
      await expect(loginTab).toBeVisible();
      await loginTab.click();
      await expect(page.getByRole("heading", { name: "Teilnehmer", exact: true })).toBeVisible();
      await page.screenshot({ path: `test-results/unified-participants-${width}-${theme}.png`, fullPage: true });
    });
  }
}
