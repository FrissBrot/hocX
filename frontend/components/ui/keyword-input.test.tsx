import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it } from "vitest";

import { KeywordInput, mergeKeywords, splitKeywords } from "./keyword-input";

function Harness({ initial = [] as string[] }) {
  const [value, setValue] = useState<string[]>(initial);
  return (
    <>
      <KeywordInput value={value} onChange={setValue} label="Keywords" />
      <output data-testid="value">{value.join("|")}</output>
    </>
  );
}

const value = () => screen.getByTestId("value").textContent;

describe("KeywordInput (Tastaturvertrag)", () => {
  it("übernimmt mit Enter und Komma, ohne Duplikate (Gross-/Kleinschreibung egal)", () => {
    render(<Harness />);
    const input = screen.getByLabelText("Keywords", { selector: "input" });
    fireEvent.change(input, { target: { value: "Velo" } });
    fireEvent.keyDown(input, { key: "Enter" });
    fireEvent.change(input, { target: { value: "Sonnenuntergang" } });
    fireEvent.keyDown(input, { key: "," });
    fireEvent.change(input, { target: { value: "velo" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(value()).toBe("Velo|Sonnenuntergang");
    expect(input).toHaveValue("");
  });

  it("Rücktaste im leeren Feld entfernt den letzten Begriff, Entfernen-Knopf einen bestimmten", () => {
    render(<Harness initial={["a1", "b2", "c3"]} />);
    const input = screen.getByLabelText("Keywords", { selector: "input" });
    fireEvent.keyDown(input, { key: "Backspace" });
    expect(value()).toBe("a1|b2");
    fireEvent.click(screen.getByRole("button", { name: "a1 entfernen" }));
    expect(value()).toBe("b2");
    expect(input).toHaveFocus();
  });

  it("übernimmt angefangenen Text beim Verlassen und trennt Eingefügtes", () => {
    render(<Harness />);
    const input = screen.getByLabelText("Keywords", { selector: "input" });
    fireEvent.change(input, { target: { value: "Gipfel" } });
    fireEvent.blur(input);
    fireEvent.paste(input, { clipboardData: { getData: () => "Seil; Karabiner\nHelm" } });
    expect(value()).toBe("Gipfel|Seil|Karabiner|Helm");
  });

  it("nur lesend: keine Eingabe, keine Entfernen-Knöpfe", () => {
    render(<KeywordInput value={["Fest"]} onChange={() => {}} label="Keywords" readOnly />);
    expect(screen.queryByRole("textbox")).toBeNull();
    expect(screen.queryByRole("button")).toBeNull();
    expect(screen.getByText("Fest")).toBeInTheDocument();
  });

  it("Hilfsfunktionen", () => {
    expect(splitKeywords(" a , b;;c\n ")).toEqual(["a", "b", "c"]);
    expect(mergeKeywords(["Velo"], ["VELO", "Rad"])).toEqual(["Velo", "Rad"]);
  });
});
