import { expect, test } from "@playwright/test";
import fs from "node:fs/promises";

import { authFiles } from "./auth";

// Auth-Audit 2026-11-20: Profil › Sicherheit › «Angemeldete Geräte» gegen das echte Backend
// (Session-Register). Die Session aus auth.setup.ts entstand nach dem Update und erscheint als
// «Dieses Gerät»; der Direktlink ?profile=security aus den Sicherheitsmails öffnet den Reiter.
test.use({ storageState: authFiles.writer });

test("Geräteliste zeigt die eigene Session und meldet ein anderes Gerät ab", async ({ page, browser }) => {
  // Zweite Anmeldung desselben Kontos (anderes «Gerät») über die API
  const other = await browser.newContext({ storageState: { cookies: [], origins: [] } });
  const login = await other.request.post("/api/auth/login", {
    data: { email: process.env.E2E_WRITER_EMAIL ?? "writer@hocx.local", password: process.env.E2E_USER_PASSWORD ?? "ChangeMe123!" },
  });
  test.skip(!login.ok(), "Zweites Login im Stack nicht möglich");

  await page.goto("/?profile=security");
  // Texte in der Sprache des Kontos (der Demo-Writer hat Englisch, Cookie hocx_locale)
  const locale = (await page.context().cookies()).find((cookie) => cookie.name === "hocx_locale")?.value ?? "de";
  const t = JSON.parse(await fs.readFile(`messages/${locale}/security.json`, "utf8")).sessions;
  // Erstes Öffnen des nachgeladenen Profil-Dialogs: der Dev-Server kompiliert ihn erst
  await expect(page.getByRole("heading", { name: t.title })).toBeVisible({ timeout: 30_000 });
  // «Dieses Gerät» steht bei der Sitzung und bei den bekannten Geräten
  await expect(page.getByText(t.current).first()).toBeVisible();
  const signOut = page.getByRole("button", { name: t.revoke, exact: true });
  await expect(signOut.first()).toBeVisible();

  // Einzeln abmelden (nicht «Alle anderen»: das beendete über session_revoke_at auch die
  // gespeicherten Sessions der übrigen Specs)
  for (let round = 0; round < 10 && (await signOut.count()) > 0; round++) {
    await signOut.first().click();
    // Rückfrage (useConfirm) ist ein alertdialog über dem Profil-Dialog
    await page.getByRole("alertdialog").getByRole("button", { name: t.revoke, exact: true }).click();
    await expect(page.getByText(t.revoked)).toBeVisible();
  }
  await expect(signOut).toHaveCount(0);

  // Die andere Session ist beendet
  const session = await other.request.get("/api/auth/session");
  expect((await session.json()).authenticated).toBe(false);
  await other.close();
});
