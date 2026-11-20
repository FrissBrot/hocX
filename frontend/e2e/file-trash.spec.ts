import { test, expect } from "@playwright/test";
import { authFiles } from "./auth";

// Papierkorb für Dateien und Fotos (Migration 0199, backend/app/services/file_trash_service.py):
// Löschen auf der Dateien-Seite legt in den Papierkorb, die Datei verschwindet aus der Liste,
// «Wiederherstellen» bringt sie zurück, «Endgültig löschen» entfernt sie nach Rückfrage.
test.use({ storageState: authFiles.admin });

test("a deleted file goes to the trash, can be restored and deleted permanently", async ({ page, request }) => {
  const stem = `e2e-papierkorb-${Date.now()}`;
  const name = `${stem}.txt`;
  const uploaded = await request.post("/api/files/document-uploads", {
    multipart: { files: { name, mimeType: "text/plain", buffer: Buffer.from(`Papierkorb ${name}`) } },
  });
  expect(uploaded.ok(), await uploaded.text()).toBeTruthy();

  await page.goto("/files");
  const row = page.locator("tr, li", { hasText: stem }).first();
  await expect(row).toBeVisible();

  // Löschen: in den Papierkorb (mit Rückfrage), danach nicht mehr in der Liste.
  await row.getByRole("button", { name: "Weitere Aktionen" }).click();
  await page.getByRole("menuitem", { name: "In den Papierkorb" }).click();
  await page.getByRole("alertdialog").getByRole("button", { name: "In den Papierkorb" }).click();
  await expect(page.locator("tr, li", { hasText: stem })).toHaveCount(0);

  // Papierkorb: Eintrag mit Restlaufzeit, wiederherstellen.
  await page.getByRole("button", { name: "Papierkorb", exact: true }).click();
  const trash = page.getByRole("dialog", { name: "Papierkorb" });
  const trashRow = trash.locator("tr", { hasText: name });
  await expect(trashRow).toBeVisible();
  await expect(trashRow).toContainText("Noch 30 Tage");
  await trashRow.getByRole("button", { name: "Wiederherstellen" }).click();
  await expect(trash.locator("tr", { hasText: name })).toHaveCount(0);
  await trash.getByRole("button", { name: "Schliessen" }).first().click();
  // Die Liste zeigt eine fertig verarbeitete Datei unter dem Namen ihrer PDF-Ansicht («….pdf»):
  // nach dem Namen ohne Endung suchen, sonst hängt der Test an der Dokumentverarbeitung.
  await expect(page.locator("tr, li", { hasText: stem }).first()).toBeVisible();

  // Erneut löschen und im Papierkorb endgültig löschen.
  await page.locator("tr, li", { hasText: stem }).first().getByRole("button", { name: "Weitere Aktionen" }).click();
  await page.getByRole("menuitem", { name: "In den Papierkorb" }).click();
  await page.getByRole("alertdialog").getByRole("button", { name: "In den Papierkorb" }).click();
  await page.getByRole("button", { name: "Papierkorb", exact: true }).click();
  await trash.locator("tr", { hasText: name }).getByRole("button", { name: "Endgültig löschen" }).click();
  await page.getByRole("alertdialog").getByRole("button", { name: "Endgültig löschen" }).click();
  await expect(trash.locator("tr", { hasText: name })).toHaveCount(0);

  const listing = await request.get("/api/files/trash");
  expect(listing.ok()).toBeTruthy();
  expect(((await listing.json()).items as { original_name: string }[]).some((item) => item.original_name === name)).toBe(false);
});
