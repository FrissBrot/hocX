import { test, expect } from "@playwright/test";
import { authFiles } from "./auth";

// 1.4.1: «Pendenz erstellen» im Aufbau von «Pendenz bearbeiten»; Anzeigename beim Erfassen eines
// Mitglieds aus Vor- und Nachname, solange er nicht von Hand geändert wurde.

test.use({ storageState: authFiles.admin });

test("Pendenz erstellen: gleicher Aufbau wie Bearbeiten, Pendenz erscheint in der Liste", async ({ page }, testInfo) => {
  const task = `E2E Neue Pendenz ${Date.now()}`;
  await page.goto("/todos", { timeout: 30_000 });
  await page.getByRole("button", { name: "+ Pendenz" }).first().click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByText("Neue Pendenz")).toBeVisible();
  await expect(dialog.locator(".todo-edit-sidebar")).toBeVisible();
  await dialog.getByRole("textbox", { name: "Aufgabe" }).fill(task);
  await dialog.getByRole("button", { name: "In Arbeit" }).click();
  await page.screenshot({ path: testInfo.outputPath("pendenz-erstellen.png") });
  await dialog.getByRole("button", { name: "Pendenz erstellen" }).click();
  await expect(dialog).toBeHidden();
  await expect(page.getByText(task)).toBeVisible();
});

test("Mitglied erfassen: Anzeigename folgt Vor- und Nachname, eigene Eingabe bleibt", async ({ page }) => {
  await page.goto("/participants", { timeout: 30_000 });
  await page.getByRole("button", { name: "Neues Mitglied" }).first().click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("Vorname", { exact: true }).fill("Test");
  await dialog.getByLabel("Nachname", { exact: true }).fill("Timo");
  const displayName = dialog.getByLabel("Anzeigename", { exact: true });
  await expect(displayName).toHaveValue("Test Timo");
  await displayName.fill("Timo T.");
  await dialog.getByLabel("Nachname", { exact: true }).fill("Weber");
  await expect(displayName).toHaveValue("Timo T.");
});
