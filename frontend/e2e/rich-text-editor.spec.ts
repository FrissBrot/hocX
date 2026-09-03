import { test, expect } from "@playwright/test";

// Regression test for a bug where the "Standard- oder Fixinhalt" field in the
// element/block editor looked fully rendered but silently ate every keystroke.
// Root cause: RichTextEditor renders its own toolbar <button>s before the
// contenteditable area, and the field was wrapped in a <label> - clicking
// anywhere in a <label> (including a non-labelable contenteditable child)
// focuses the *first* labelable descendant, which was the Bold button, not
// the editor. Fixed by using a plain <div> wrapper instead of <label>.
test("rich text field in the create-element form accepts typed input", async ({ page }) => {
  await page.goto("/elements");
  await page.getByRole("button", { name: "Neues Element" }).click();

  // Any block type card exposes the same "Standard- oder Fixinhalt" field.
  await page.locator(".block-type-card").first().click();

  const editor = page.locator(".rich-text-editor-content").first();
  await editor.scrollIntoViewIfNeeded();
  await editor.click();
  await expect(page.evaluate(() => (document.activeElement as HTMLElement | null)?.isContentEditable)).resolves.toBe(true);

  await page.keyboard.type("E2E Rich Text Check");
  await expect(editor).toContainText("E2E Rich Text Check");

  // Guards a related fix: the value-sync effect used to compare against the
  // editor's live document instead of its own last-emitted value, so a
  // render lagging behind fast typing could reset content mid-keystroke.
  await page.keyboard.press("Control+a");
  await page.keyboard.press("Backspace");
  await page.keyboard.type("FastTypedWithNoDelay", { delay: 0 });
  await expect(editor).toHaveText("FastTypedWithNoDelay");

  // Discard - this test only exercises the field, it doesn't need to persist anything.
  await page.getByRole("button", { name: "Schliessen" }).click();
});
