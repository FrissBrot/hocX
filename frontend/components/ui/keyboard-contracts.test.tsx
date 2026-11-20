/**
 * Tastaturverträge der gemeinsamen Bausteine (design/KEYBOARD_ACCESSIBILITY.md): getestet wird
 * Verhalten - wohin der Fokus geht, was Tasten auslösen -, nicht das Vorhandensein von Handlern.
 * Echte Browser-Tab-Reihenfolge prüft zusätzlich e2e/keyboard-navigation.spec.ts.
 */
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { ConfirmProvider, useConfirm } from "@/contexts/confirm-context";
import { getTabbables, MAIN_CONTENT_ID, wrapTab } from "@/lib/a11y/focus";

import { ActionMenu } from "./action-menu";
import { FilterTabs } from "./filter-tabs";
import { HelpPopover } from "./help-popover";
import { Modal } from "./modal";
import { SearchableMultiSelect, SearchableSelect } from "./searchable-select";
import { TagInput } from "./tag-input";
import { Tabs } from "./tabs";

describe("Fokus-Hilfen", () => {
  it("getTabbables überspringt Deaktiviertes, tabindex=-1 und Verstecktes", () => {
    document.body.innerHTML = `
      <div id="root">
        <button id="a">a</button>
        <button disabled>b</button>
        <button tabindex="-1">c</button>
        <div hidden><button>d</button></div>
        <button style="display:none">e</button>
        <fieldset disabled><input id="f" /></fieldset>
        <a href="#x" id="g">g</a>
        <div tabindex="0" id="h">h</div>
      </div>`;
    expect(getTabbables(document.getElementById("root")).map((element) => element.id)).toEqual(["a", "g", "h"]);
  });

  it("wrapTab hält den Fokus im Container, auch wenn er auf <body> verloren ging", () => {
    document.body.innerHTML = '<div id="root"><button id="first">1</button><button id="last">2</button></div>';
    const root = document.getElementById("root")!;
    const event = { key: "Tab", shiftKey: false, preventDefault: vi.fn() };
    (document.activeElement as HTMLElement | null)?.blur();
    expect(wrapTab(event, root)).toBe(true);
    expect(document.activeElement?.id).toBe("first");
    document.getElementById("last")!.focus();
    wrapTab(event, root);
    expect(document.activeElement?.id).toBe("first");
    wrapTab({ ...event, shiftKey: true }, root);
    expect(document.activeElement?.id).toBe("last");
  });
});

describe("ActionMenu (Menü-Button nach WAI-ARIA APG)", () => {
  function Fixture({ onEdit = vi.fn(), onDelete = vi.fn() }) {
    return (
      <>
        <ActionMenu ariaLabel="Aktionen Zeile" items={[{ label: "Bearbeiten", onClick: onEdit }, { label: "Löschen", onClick: onDelete, danger: true }]} />
        <button type="button">Danach</button>
      </>
    );
  }

  it("öffnet mit Fokus auf dem ersten Eintrag, Pfeile wandern, Escape gibt den Fokus zurück", () => {
    render(<Fixture />);
    const trigger = screen.getByRole("button", { name: "Aktionen Zeile" });
    expect(trigger).toHaveAttribute("aria-haspopup", "menu");
    trigger.focus();
    fireEvent.keyDown(trigger, { key: "ArrowDown" });
    expect(trigger).toHaveAttribute("aria-expanded", "true");
    const menu = screen.getByRole("menu", { name: "Aktionen Zeile" });
    const [edit, remove] = within(menu).getAllByRole("menuitem");
    expect(edit).toHaveFocus();
    fireEvent.keyDown(edit, { key: "ArrowDown" });
    expect(remove).toHaveFocus();
    fireEvent.keyDown(remove, { key: "ArrowDown" });
    expect(edit).toHaveFocus();
    fireEvent.keyDown(edit, { key: "End" });
    expect(remove).toHaveFocus();
    fireEvent.keyDown(remove, { key: "Escape" });
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
  });

  it("Auswahl per Enter führt die Aktion aus und lässt den Fokus nicht auf <body> fallen", () => {
    const onEdit = vi.fn();
    render(<Fixture onEdit={onEdit} />);
    const trigger = screen.getByRole("button", { name: "Aktionen Zeile" });
    trigger.focus();
    fireEvent.click(trigger);
    const edit = screen.getByRole("menuitem", { name: "Bearbeiten" });
    expect(edit).toHaveFocus();
    // Enter auf einem <button> löst im Browser click aus
    fireEvent.click(edit);
    expect(onEdit).toHaveBeenCalledTimes(1);
    expect(trigger).toHaveFocus();
  });

  it("Tab verlässt das Menü über den Auslöser und schliesst es", () => {
    render(<Fixture />);
    const trigger = screen.getByRole("button", { name: "Aktionen Zeile" });
    trigger.focus();
    fireEvent.click(trigger);
    fireEvent.keyDown(screen.getByRole("menuitem", { name: "Bearbeiten" }), { key: "Tab" });
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
    // Der Browser setzt die Tab-Reihenfolge ab dem Auslöser fort (in jsdom ohne Standardaktion)
    expect(trigger).toHaveFocus();
  });
});

describe("Rückfrage (useConfirm)", () => {
  function Fixture({ onResult }: { onResult: (value: boolean) => void }) {
    const confirm = useConfirm();
    return (
      <button type="button" onClick={async () => onResult(await confirm({ message: "Wirklich löschen?", tone: "danger" }))}>
        Löschen
      </button>
    );
  }

  it("startet auf «Abbrechen», hält Tab im Dialog und gibt den Fokus zurück", async () => {
    const onResult = vi.fn();
    render(
      <ConfirmProvider>
        <Fixture onResult={onResult} />
      </ConfirmProvider>
    );
    const opener = screen.getByRole("button", { name: "Löschen" });
    opener.focus();
    await act(async () => {
      fireEvent.click(opener);
    });
    const dialog = screen.getByRole("alertdialog");
    expect(dialog).toHaveAccessibleDescription("Wirklich löschen?");
    const cancel = within(dialog).getByRole("button", { name: "Abbrechen" });
    expect(cancel).toHaveFocus();
    const confirmButton = within(dialog).getAllByRole("button").at(-1)!;
    confirmButton.focus();
    fireEvent.keyDown(confirmButton, { key: "Tab" });
    expect(cancel).toHaveFocus();
    fireEvent.keyDown(cancel, { key: "Tab", shiftKey: true });
    expect(confirmButton).toHaveFocus();
    await act(async () => {
      fireEvent.keyDown(confirmButton, { key: "Escape" });
    });
    expect(onResult).toHaveBeenCalledWith(false);
    expect(opener).toHaveFocus();
  });
});

describe("Modal", () => {
  it("gibt den Fokus an den Hauptinhalt, wenn der Auslöser inzwischen entfernt wurde", async () => {
    function Fixture() {
      const [open, setOpen] = useState(false);
      const [rowVisible, setRowVisible] = useState(true);
      return (
        <main id={MAIN_CONTENT_ID} tabIndex={-1}>
          {rowVisible ? <button type="button" onClick={() => setOpen(true)}>Zeile öffnen</button> : null}
          <Modal open={open} title="Zeile" onClose={() => setOpen(false)}>
            <button type="button" onClick={() => { setRowVisible(false); setOpen(false); }}>Zeile löschen</button>
          </Modal>
        </main>
      );
    }
    render(<Fixture />);
    const opener = screen.getByRole("button", { name: "Zeile öffnen" });
    opener.focus();
    await act(async () => {
      fireEvent.click(opener);
    });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Zeile löschen" }));
    });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(document.activeElement?.id).toBe(MAIN_CONTENT_ID);
  });

  it("ist über den Titel benannt", () => {
    render(<Modal open title="Termin bearbeiten" description="Alle Felder" onClose={vi.fn()}><input aria-label="Name" /></Modal>);
    expect(screen.getByRole("dialog", { name: "Termin bearbeiten" })).toHaveAccessibleDescription("Alle Felder");
  });
});

describe("Tabs und FilterTabs (roving tabindex)", () => {
  it("Tabs: ein Tab-Halt, Pfeile/Pos1/Ende wechseln und zeigen das Panel", () => {
    render(
      <Tabs
        tabs={[
          { id: "a", label: "Allgemein", content: <p>Inhalt A</p> },
          { id: "b", label: "Rechte", content: <p>Inhalt B</p> },
          { id: "c", label: "Verlauf", content: <p>Inhalt C</p> },
        ]}
      />
    );
    const tabs = screen.getAllByRole("tab");
    expect(tabs.map((tab) => tab.tabIndex)).toEqual([0, -1, -1]);
    tabs[0].focus();
    fireEvent.keyDown(tabs[0], { key: "ArrowRight" });
    expect(tabs[1]).toHaveFocus();
    expect(tabs[1]).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tabpanel", { name: "Rechte" })).toHaveTextContent("Inhalt B");
    fireEvent.keyDown(tabs[1], { key: "End" });
    expect(tabs[2]).toHaveFocus();
    fireEvent.keyDown(tabs[2], { key: "ArrowRight" });
    expect(tabs[0]).toHaveFocus();
  });

  it("FilterTabs wählen den Filter mit den Pfeilen", () => {
    const onChange = vi.fn();
    render(<FilterTabs options={[{ value: "open", label: "Offen" }, { value: "done", label: "Erledigt" }]} value="open" onChange={onChange} />);
    const open = screen.getByRole("tab", { name: "Offen" });
    open.focus();
    fireEvent.keyDown(open, { key: "ArrowRight" });
    expect(onChange).toHaveBeenCalledWith("done");
    expect(screen.getByRole("tab", { name: "Erledigt" })).toHaveFocus();
  });
});

describe("SearchableSelect (Combobox)", () => {
  const options = [
    { id: 1, name: "Anna" },
    { id: 2, name: "Bruno" },
    { id: 3, name: "Carla" },
  ];

  it("Pfeil runter öffnet, Markierung per aria-activedescendant, Enter wählt, Fokus zurück auf den Auslöser", () => {
    const onChange = vi.fn();
    render(<SearchableSelect options={options} getId={(o) => o.id} getLabel={(o) => o.name} value={null} onChange={onChange} placeholder="Person" />);
    const trigger = screen.getByRole("button", { name: "Person" });
    trigger.focus();
    fireEvent.keyDown(trigger, { key: "ArrowDown" });
    const combo = screen.getByRole("combobox");
    expect(combo).toHaveFocus();
    // Optionen sind keine eigenen Tab-Halte
    expect(screen.getAllByRole("option").every((option) => option.tabIndex === -1)).toBe(true);
    fireEvent.keyDown(combo, { key: "ArrowDown" });
    const active = document.getElementById(combo.getAttribute("aria-activedescendant")!);
    expect(active).toHaveTextContent("Bruno");
    fireEvent.keyDown(combo, { key: "Enter" });
    expect(onChange).toHaveBeenCalledWith(options[1]);
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
  });

  it("Mehrfachauswahl: Enter schaltet um, die Liste bleibt offen, Escape schliesst", () => {
    function Fixture() {
      const [values, setValues] = useState<number[]>([]);
      return <SearchableMultiSelect options={options} getId={(o) => o.id} getLabel={(o) => o.name} values={values} onChange={setValues} placeholder="Personen" />;
    }
    render(<Fixture />);
    const trigger = screen.getByRole("button", { name: "Personen" });
    trigger.focus();
    fireEvent.click(trigger);
    const combo = screen.getByRole("combobox");
    fireEvent.keyDown(combo, { key: "End" });
    fireEvent.keyDown(combo, { key: "Enter" });
    expect(screen.getByRole("option", { name: "Carla" })).toHaveAttribute("aria-selected", "true");
    expect(combo).toHaveFocus();
    fireEvent.keyDown(combo, { key: "Escape" });
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
  });
});

describe("TagInput", () => {
  function Fixture({ initial = "" }: { initial?: string }) {
    const [value, setValue] = useState(initial);
    return <TagInput value={value} onChange={setValue} suggestions={["Vorstand", "Kasse"]} />;
  }

  it("Vorschläge sind per Tastatur erreichbar und lösen mit Enter/Klick aus (nicht nur per Zeiger)", () => {
    render(<Fixture />);
    const input = screen.getByPlaceholderText("Tag hinzufügen…");
    input.focus();
    fireEvent.focus(input);
    fireEvent.keyDown(input, { key: "ArrowDown" });
    const first = screen.getByRole("button", { name: "Vorstand" });
    expect(first).toHaveFocus();
    fireEvent.keyDown(first, { key: "ArrowDown" });
    expect(screen.getByRole("button", { name: "Kasse" })).toHaveFocus();
    // Enter auf einem fokussierten <button> = click
    fireEvent.click(screen.getByRole("button", { name: "Kasse" }));
    expect(screen.getByRole("button", { name: "Tag Kasse entfernen" })).toBeInTheDocument();
  });

  it("Entfernen-Knöpfe der Tags sind Tab-Halte", () => {
    render(<Fixture initial="Vorstand" />);
    expect(screen.getByRole("button", { name: "Tag Vorstand entfernen" }).tabIndex).toBe(0);
  });
});

describe("HelpPopover", () => {
  it("legt den Fokus auf die Erklärung und Escape führt zurück zum «?»", () => {
    render(<HelpPopover topic="Fälligkeit">Bis wann die Pendenz erledigt sein soll.</HelpPopover>);
    const trigger = screen.getByRole("button", { name: /Fälligkeit/ });
    trigger.focus();
    fireEvent.click(trigger);
    const panel = screen.getByRole("dialog");
    expect(panel).toHaveFocus();
    fireEvent.keyDown(panel, { key: "Escape" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
  });
});
