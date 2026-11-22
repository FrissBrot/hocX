import { randomBytes } from "node:crypto";
import { expect, test } from "@playwright/test";

// Konzept «Personen an einem Ort»: Login und Stammdaten einer Person auf der Personenseite.
test("Personenseite: Login vergeben, Stammdaten speichern und Login entziehen", async ({ request, page }) => {
  // Erstkompilierung der Detailroute und ggf. «Identität bestätigen» brauchen im vollen Lauf mehr als 45 s
  test.setTimeout(90_000);
  const name = `Identität ${Date.now()}`;
  const response = await request.post("/api/participants", {
    data: { display_name: name, email: `identity-${Date.now()}@example.invalid` },
  });
  expect(response.ok(), await response.text()).toBeTruthy();
  const participant = await response.json();
  try {
    expect(participant.login_enabled).toBe(false);
    const users = await (await request.get("/api/users")).json();
    expect(users.find((user: { id: string }) => user.id === participant.id)).toBeTruthy();

    // Liste: Zeile öffnet die Personenseite
    await page.goto("/participants");
    await page.getByText(name, { exact: true }).click();
    // Erster Aufruf der Detailroute: der Dev-Server des E2E-Stacks kompiliert sie erst (> 5 s möglich)
    await expect(page).toHaveURL(new RegExp(`/participants/${participant.id}$`), { timeout: 30_000 });
    await expect(page.getByRole("heading", { name, exact: true })).toBeVisible();

    // Login per Passwort vergeben
    await page.getByRole("button", { name: "Passwort setzen", exact: true }).click();
    const dialog = page.getByRole("dialog", { name: "Login für Identität" });
    // Passwortregel (backend app/core/password_policy.py): zur Laufzeit, ohne häufige Wörter
    await dialog.getByLabel(/^Passwort/).fill(`Pers-${randomBytes(12).toString("base64url")}-7q`);
    await dialog.getByRole("button", { name: "Login aktivieren", exact: true }).click();
    // Ist die Anmeldung der Testsitzung älter als auth_step_up_admin_minutes (15 min, im vollen
    // Lauf je nach Reihenfolge), verlangt das Backend erst «Identität bestätigen» - mit Passwort.
    const stepUp = page.getByRole("dialog", { name: "Identität bestätigen" });
    await expect.poll(async () => (await stepUp.isVisible()) || !(await dialog.isVisible()), { timeout: 10_000 }).toBe(true);
    if (await stepUp.isVisible().catch(() => false)) {
      const passwordMethod = stepUp.getByRole("tab", { name: "Passwort", exact: true }).or(stepUp.getByRole("radio", { name: "Passwort", exact: true }));
      if (await passwordMethod.count()) await passwordMethod.first().click();
      await stepUp.getByLabel("Dein Passwort").fill(process.env.E2E_USER_PASSWORD ?? "ChangeMe123!");
      await stepUp.getByRole("button", { name: "Bestätigen", exact: true }).click();
      await expect(stepUp).not.toBeVisible();
    }
    await expect(dialog).not.toBeVisible();
    await expect(page.getByText("Login aktiv", { exact: true }).first()).toBeVisible();
    const updatedUsers = await (await request.get("/api/users")).json();
    expect(updatedUsers.find((user: { id: string }) => user.id === participant.id).login_enabled).toBe(true);

    // Stammdaten: Leiste «Ungespeicherte Änderungen» speichert
    await page.getByLabel("Anzeigename", { exact: true }).fill(`${name} neu`);
    const bar = page.getByRole("region", { name: "Ungespeicherte Änderungen" });
    await expect(bar).toBeVisible();
    await bar.getByRole("button", { name: "Speichern", exact: true }).click();
    await expect(bar).not.toBeVisible();
    const saved = await (await request.get(`/api/participants/${participant.id}`)).json();
    expect(saved.display_name).toBe(`${name} neu`);
    expect(saved.login_status).toBe("active");

    // Login entziehen
    await page.getByRole("button", { name: "Login entziehen", exact: true }).click();
    await page.getByRole("alertdialog").or(page.getByRole("dialog")).getByRole("button", { name: "Login entziehen", exact: true }).click();
    await expect(page.getByText("Kein Login", { exact: true }).first()).toBeVisible();
  } finally {
    await request.delete(`/api/participants/${participant.id}`);
  }
});

test("Zugriff: Übersicht und Sicherheit mit MFA-Pflicht", async ({ page }) => {
  await page.goto("/users");
  await expect(page.getByRole("heading", { name: "Wer hat Zugriff", exact: true })).toBeVisible();
  await expect(page.getByRole("tab", { name: /^MFA fehlt/ })).toBeVisible();
  await page.goto("/users/security");
  await expect(page.getByRole("switch", { name: /MFA für alle Logins verlangen/ })).toBeVisible();
});

for (const width of [1440, 390]) {
  for (const theme of ["light", "dark"]) {
    test(`Teilnehmeransichten ${width}px ${theme}`, async ({ page }) => {
      await page.setViewportSize({ width, height: 1000 });
      await page.addInitScript((value) => localStorage.setItem("hocx-theme", value), theme);
      await page.goto("/participants");
      await page.evaluate((value) => document.documentElement.setAttribute("data-theme", value), theme);
      if (width === 390) {
        const loginTab = page.getByRole("button", { name: /^Mit Login/ });
        await expect(loginTab).toBeVisible();
        await loginTab.click();
      } else {
        await expect(page.getByText("Login", { exact: true }).first()).toBeVisible();
      }
      await expect(page.getByRole("heading", { name: "Mitglieder", exact: true })).toBeVisible();
      await page.screenshot({ path: `test-results/unified-participants-${width}-${theme}.png`, fullPage: true });
    });
  }
}
