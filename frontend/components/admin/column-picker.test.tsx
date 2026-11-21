import { fireEvent, render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { afterEach, describe, expect, it } from "vitest";

import messages from "@/messages/de/adminShell.json";
import { ColumnPicker, defaultVisibleColumns, readVisibleColumns, useColumnVisibility, type ColumnDef } from "./column-picker";

const columns: ColumnDef[] = [
  { key: "name", label: "Name", required: true },
  { key: "email", label: "E-Mail" },
  { key: "mfa", label: "MFA", hidden: true },
];

function Harness() {
  const cols = useColumnVisibility("test", columns);
  return (
    <>
      <ColumnPicker columns={columns} isVisible={cols.isVisible} onToggle={cols.toggle} />
      <output data-testid="visible">{cols.visible.join(",")}</output>
    </>
  );
}

describe("Spaltenwahl", () => {
  afterEach(() => window.localStorage.clear());

  it("Standard: Pflicht- und nicht versteckte Spalten", () => {
    expect(defaultVisibleColumns(columns)).toEqual(["name", "email"]);
  });

  it("liest gespeicherte Auswahl, Pflichtspalten bleiben, Unbekanntes fällt weg", () => {
    window.localStorage.setItem("hocx-admin-cols:test", JSON.stringify(["mfa", "unbekannt"]));
    expect(readVisibleColumns("test", columns)).toEqual(["name", "mfa"]);
    window.localStorage.setItem("hocx-admin-cols:test", "kaputt");
    expect(readVisibleColumns("test", columns)).toEqual(["name", "email"]);
  });

  it("schaltet per Tastatur/Klick um und speichert", () => {
    render(
      <NextIntlClientProvider locale="de" messages={{ adminShell: messages }}>
        <Harness />
      </NextIntlClientProvider>,
    );
    fireEvent.click(screen.getByRole("button", { name: "Spalten" }));
    const mfa = screen.getByRole("checkbox", { name: "MFA" });
    fireEvent.click(mfa);
    expect(screen.getByTestId("visible").textContent).toBe("name,email,mfa");
    expect(JSON.parse(window.localStorage.getItem("hocx-admin-cols:test") ?? "[]")).toEqual(["name", "email", "mfa"]);
    expect(screen.getByRole("checkbox", { name: "Name" })).toBeDisabled();
  });
});
