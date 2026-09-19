import { test, expect, request as playwrightRequest } from "@playwright/test";
import path from "node:path";
import { authFiles } from "./auth";

// Gallery upload with a Zyklus target (see gallery-upload-modal.tsx's "Bezug" picker /
// files.py's upload_gallery_images cycle_config_id branch): a writer can pick a Zyklus while
// uploading through the "Fotos" gallery window so the batch lands directly in that cycle's
// auto-generated Zyklus/Periode album (photo_album_service.get_or_create_cycle_album), not
// just the plain gallery. No E2E spec drove this target picker through the real page before.
test.use({ storageState: authFiles.admin });

test("uploading with a Zyklus target puts the photo in that cycle's auto-album", async ({ page, request }) => {
  const suffix = `${Date.now()}`;
  const cycleName = `E2E Zyklus ${suffix}`;

  const created = await request.post("/api/cycle-configs", {
    data: { name: cycleName, name_pattern: `${cycleName} [cy]` },
  });
  expect(created.ok(), await created.text()).toBeTruthy();
  const cycleConfig = await created.json();

  try {
    await page.goto("/photos");
    await page.getByRole("button", { name: "+ Bilder hochladen" }).click();

    const modal = page.getByRole("dialog", { name: "Bilder hochladen" });

    // File first, target picker second - the other order (radio/select before the file is
    // attached) silently drops the already-selected file back to none by the time the
    // upload button is clicked, seemingly independent of this test (the same happens via
    // direct setInputFiles on the hidden input, not just this filechooser flow) - worth a
    // closer look outside this test's scope, but not this audit fix's regression.
    const fileChooserPromise = page.waitForEvent("filechooser");
    await modal.getByText("Bilder hierher ziehen").click();
    const fileChooser = await fileChooserPromise;
    await fileChooser.setFiles(path.resolve("e2e/fixtures/photos/sample.png"));
    await expect(modal.locator(".gallery-upload-file-list")).toContainText("sample.png");

    // Both pickers are SearchableSelects (mini-menu popovers), not native controls - see
    // upload-target-fields.tsx: first the "Bezug" kind, which then reveals a second picker
    // for the concrete Zyklus.
    await modal.locator(".mini-menu-trigger").first().click();
    await page.getByRole("option", { name: "Zyklus", exact: true }).click();
    await modal.locator(".mini-menu-trigger").nth(1).click();
    await page.getByRole("option", { name: cycleName }).click();

    const uploaded = page.waitForResponse((r) => r.url().endsWith("/api/files/gallery-uploads") && r.request().method() === "POST");
    await page.getByRole("button", { name: "1 Bild hochladen" }).click();
    const uploadResponse = await uploaded;
    expect(uploadResponse.ok(), await uploadResponse.text()).toBeTruthy();
    // The upload request only stages the file and queues a gallery_upload_job now (see
    // upload_gallery_images) - actual ingestion/album-assignment happens afterwards, in the
    // background (app/main.py's gallery_upload_ingest_loop), so wait for that job to finish
    // before checking the album.
    const job = await uploadResponse.json();
    await expect
      .poll(
        async () => {
          const detail = await request.get(`/api/files/gallery-upload-jobs/${job.id}`);
          return (await detail.json()).status;
        },
        { timeout: 30_000 }
      )
      .toBe("done");

    await page.getByRole("tab", { name: "Alben" }).click();
    const albumCard = page.locator(".album-card", { hasText: cycleName });
    await expect(albumCard).toBeVisible();
    await expect(albumCard.getByText(/^1 Foto$/)).toBeVisible();
  } finally {
    await request.delete(`/api/cycle-configs/${cycleConfig.id}`).catch(() => {});
  }
});
