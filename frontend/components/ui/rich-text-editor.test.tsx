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
