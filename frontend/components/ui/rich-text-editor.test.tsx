import { act, render, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";

import { RichTextEditor } from "./rich-text-editor";

// Öffnen eines Protokolls darf nichts speichern: Tiptap meldet bei setEditable (und anderen
// Transaktionen ohne Textänderung) ein «update», das früher als onChange mit unverändertem
// Inhalt durchging und ein Speichern samt «Änderungen noch nicht gespeichert» auslöste.
it("does not emit onChange on mount or when only editability changes", async () => {
  const onChange = vi.fn();
  const { container, rerender } = render(<RichTextEditor value="Die Sitzung wird **eröffnet**." onChange={onChange} />);
  await waitFor(() => expect(container.querySelector(".rich-text-editor-content")).not.toBeNull());
  await act(async () => { await new Promise((resolve) => setTimeout(resolve, 20)); });
  rerender(<RichTextEditor value="Die Sitzung wird **eröffnet**." onChange={onChange} readOnly />);
  rerender(<RichTextEditor value="Die Sitzung wird **eröffnet**." onChange={onChange} />);
  await act(async () => { await new Promise((resolve) => setTimeout(resolve, 20)); });
  expect(onChange).not.toHaveBeenCalled();
});

it("does not emit onChange for an empty block", async () => {
  const onChange = vi.fn();
  const { container } = render(<RichTextEditor value="" onChange={onChange} />);
  await waitFor(() => expect(container.querySelector(".rich-text-editor-content")).not.toBeNull());
  await act(async () => { await new Promise((resolve) => setTimeout(resolve, 20)); });
  expect(onChange).not.toHaveBeenCalled();
});

// Nackte Links erscheinen als Link (Dekoration), ohne das gespeicherte Markdown zu ändern.
it("shows bare urls and mail addresses as links without saving anything", async () => {
  const onChange = vi.fn();
  const { container } = render(
    <RichTextEditor value={"Mail: scharleitung@example.ch\n\n**Link OneDrive:** https://example.sharepoint.com/:f:/g/Eu_Dk?e=1."} onChange={onChange} />
  );
  await waitFor(() => expect(container.querySelectorAll(".rich-text-autolink")).toHaveLength(2));
  const links = [...container.querySelectorAll(".rich-text-autolink")].map((node) => node.textContent);
  expect(links).toEqual(["scharleitung@example.ch", "https://example.sharepoint.com/:f:/g/Eu_Dk?e=1"]);
  await act(async () => { await new Promise((resolve) => setTimeout(resolve, 20)); });
  expect(onChange).not.toHaveBeenCalled();
});

// Tiptap v3 rendert bei Transaktionen nicht mehr neu: die Toolbar muss den Formatstatus trotzdem
// zeigen, auch nach Strg+B ohne Auswahl (nur vorgemerkte Marke, kein onChange, kein Neu-Rendern
// durch die Eltern). Vorher blieb «B» dann unmarkiert und das Kürzel wirkte wirkungslos.
it("shows the active format in the toolbar after a shortcut without text change", async () => {
  const onChange = vi.fn();
  const { container, getByRole } = render(<RichTextEditor value="Hallo" onChange={onChange} />);
  await waitFor(() => expect(container.querySelector(".ProseMirror")).not.toBeNull());
  const editorElement = container.querySelector<HTMLElement>(".ProseMirror")!;
  const bold = getByRole("button", { name: "B" });
  const bulletList = getByRole("button", { name: "Aufzählung" });
  expect(bold).toHaveAttribute("aria-pressed", "false");
  expect(bold).toHaveAttribute("title", "Fett (Strg+B)");
  expect(bold).toHaveAttribute("aria-keyshortcuts", "Control+B Meta+B");
  expect(bulletList).toHaveAttribute("title", "Aufzählung (Strg+Umschalt+8)");

  const press = (key: string, init: KeyboardEventInit) =>
    act(() => { editorElement.dispatchEvent(new KeyboardEvent("keydown", { key, bubbles: true, cancelable: true, ...init })); });
  press("b", { ctrlKey: true, keyCode: 66 } as KeyboardEventInit);
  await waitFor(() => expect(bold).toHaveAttribute("aria-pressed", "true"));
  expect(onChange).not.toHaveBeenCalled();

  press("8", { ctrlKey: true, shiftKey: true, keyCode: 56 } as KeyboardEventInit);
  await waitFor(() => expect(bulletList).toHaveAttribute("aria-pressed", "true"));
  expect(onChange).toHaveBeenLastCalledWith("- Hallo");
});
