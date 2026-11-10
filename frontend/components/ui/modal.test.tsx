import { act, fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { Modal } from "./modal";

function Harness({ onClose = vi.fn() }: { onClose?: () => void }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>Oeffnen</button>
      <Modal open={open} title="Testdialog" onClose={() => { onClose(); setOpen(false); }}>
        <input aria-label="Name" />
        <button type="button">Speichern</button>
      </Modal>
    </>
  );
}

describe("Modal (Audit MAIN-FE-009)", () => {
  it("schliesst nicht, wenn ein Klick-Ziehen im Dialog beginnt und auf dem Backdrop endet", () => {
    const onClose = vi.fn();
    render(<Modal open title="Testdialog" onClose={onClose}><input aria-label="Name" /></Modal>);
    const dialog = screen.getByRole("dialog");
    const backdrop = dialog.parentElement!;

    fireEvent.mouseDown(screen.getByLabelText("Name"));
    fireEvent.click(backdrop);
    expect(onClose).not.toHaveBeenCalled();

    fireEvent.mouseDown(backdrop);
    fireEvent.click(backdrop);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("legt den Fokus in den Dialog, haelt Tab darin und gibt ihn beim Schliessen zurueck", async () => {
    render(<Harness />);
    const opener = screen.getByRole("button", { name: "Oeffnen" });
    opener.focus();
    await act(async () => { fireEvent.click(opener); });

    const dialog = screen.getByRole("dialog");
    expect(dialog.contains(document.activeElement)).toBe(true);

    const save = screen.getByRole("button", { name: "Speichern" });
    save.focus();
    fireEvent.keyDown(save, { key: "Tab" });
    // Erstes fokussierbares Element ist der Schliessen-Button im Kopf.
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "Schliessen" }));
    fireEvent.keyDown(document.activeElement!, { key: "Tab", shiftKey: true });
    expect(document.activeElement).toBe(save);

    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Schliessen" })); });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(document.activeElement).toBe(opener);
  });
});
