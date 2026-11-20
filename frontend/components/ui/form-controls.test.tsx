import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { NumberStepper } from "./number-stepper";
import { SegmentedControl } from "./segmented-control";
import { Switch } from "./switch";
import { TagInput } from "./tag-input";

describe("SegmentedControl", () => {
  function Harness({ onChange = vi.fn() }: { onChange?: (value: string) => void }) {
    const [value, setValue] = useState("a");
    return (
      <SegmentedControl
        aria-label="Auswahl"
        value={value}
        onChange={(next) => {
          setValue(next);
          onChange(next);
        }}
        options={[
          { value: "a", label: "Eins" },
          { value: "b", label: "Zwei", disabled: true },
          { value: "c", label: "Drei" },
        ]}
      />
    );
  }

  it("ist eine Radio-Gruppe mit einem Tab-Stopp und überspringt deaktivierte Optionen", () => {
    const onChange = vi.fn();
    render(<Harness onChange={onChange} />);
    const radios = screen.getAllByRole("radio");
    expect(screen.getByRole("radiogroup", { name: "Auswahl" })).toBeInTheDocument();
    expect(radios.map((radio) => radio.getAttribute("aria-checked"))).toEqual(["true", "false", "false"]);
    expect(radios.map((radio) => radio.tabIndex)).toEqual([0, -1, -1]);

    fireEvent.keyDown(radios[0], { key: "ArrowRight" });
    expect(onChange).toHaveBeenLastCalledWith("c");
    expect(radios[2]).toHaveFocus();
    expect(radios[2]).toHaveAttribute("aria-checked", "true");

    fireEvent.keyDown(radios[2], { key: "Home" });
    expect(onChange).toHaveBeenLastCalledWith("a");
    fireEvent.click(radios[1]);
    expect(onChange).toHaveBeenCalledTimes(2);
  });
});

describe("NumberStepper", () => {
  function Harness({ start, ...props }: { start: number | ""; min: number; max?: number; allowEmpty?: boolean; decrementToEmpty?: boolean }) {
    const [value, setValue] = useState<number | "">(start);
    return (
      <>
        <NumberStepper value={value} onChange={setValue} label="Tage" emptyLabel="sofort" {...props} />
        <output data-testid="value">{JSON.stringify(value)}</output>
      </>
    );
  }
  const value = () => JSON.parse(screen.getByTestId("value").textContent ?? "null");

  it("zählt mit «−»/«+» und Pfeiltasten innerhalb der Grenzen", () => {
    render(<Harness start={89} min={1} max={90} />);
    const input = screen.getByRole("spinbutton", { name: "Tage" });
    fireEvent.click(screen.getByRole("button", { name: "Tage erhöhen" }));
    expect(value()).toBe(90);
    expect(screen.getByRole("button", { name: "Tage erhöhen" })).toBeDisabled();
    fireEvent.keyDown(input, { key: "ArrowDown" });
    expect(value()).toBe(89);
  });

  it("setzt getippte Werte auf die Grenzen und lässt leer nur mit allowEmpty zu", () => {
    render(<Harness start={30} min={1} max={90} />);
    const input = screen.getByRole("spinbutton", { name: "Tage" });
    fireEvent.change(input, { target: { value: "500" } });
    expect(value()).toBe(90);
    fireEvent.change(input, { target: { value: "" } });
    fireEvent.blur(input);
    expect(value()).toBe(90);
    fireEvent.change(input, { target: { value: "0" } });
    fireEvent.blur(input);
    expect(value()).toBe(1);
  });

  it("leert mit «−» beim Minimum und beginnt mit «+» beim Minimum (leer = sofort)", () => {
    render(<Harness start={0} min={0} max={3650} allowEmpty />);
    const input = screen.getByRole("spinbutton", { name: "Tage" });
    fireEvent.click(screen.getByRole("button", { name: "Tage verringern" }));
    expect(value()).toBe("");
    expect(input).toHaveAttribute("placeholder", "sofort");
    expect(input).toHaveAttribute("aria-valuetext", "sofort");
    expect(screen.getByRole("button", { name: "Tage verringern" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Tage erhöhen" }));
    expect(value()).toBe(0);
  });

  it("bleibt mit decrementToEmpty=false beim Minimum stehen", () => {
    render(<Harness start={1} min={1} allowEmpty decrementToEmpty={false} />);
    expect(screen.getByRole("button", { name: "Tage verringern" })).toBeDisabled();
    fireEvent.change(screen.getByRole("spinbutton", { name: "Tage" }), { target: { value: "" } });
    expect(value()).toBe("");
  });
});

describe("Switch", () => {
  it("ist ein Schalter mit Label und Beschreibung", () => {
    const onChange = vi.fn();
    render(<Switch checked={false} onChange={onChange} label="Offen halten" help="Schliesst erst später." />);
    const control = screen.getByRole("switch", { name: "Offen halten" });
    expect(control).toHaveAccessibleDescription("Schliesst erst später.");
    fireEvent.click(control);
    expect(onChange).toHaveBeenCalledWith(true);
  });
});

describe("TagInput mit Vorschlagszeile", () => {
  function Harness() {
    const [value, setValue] = useState("lager");
    return (
      <>
        <TagInput value={value} onChange={setValue} suggestions={["lager", "bericht", "foto"]} quickSuggestions={5} extraChips={<span>auto-chip</span>} />
        <output data-testid="tags">{value}</output>
      </>
    );
  }

  it("fügt mit Enter, Komma und «+ tag» hinzu und entfernt mit Backspace das letzte", () => {
    render(<Harness />);
    const tags = () => screen.getByTestId("tags").textContent;
    const input = screen.getByRole("textbox");
    expect(screen.getByText("auto-chip")).toBeInTheDocument();
    // Vorschläge ohne bereits gewählte Tags
    expect(screen.queryByRole("button", { name: "Tag lager hinzufügen" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Tag bericht hinzufügen" }));
    expect(tags()).toBe("lager,bericht");

    fireEvent.change(input, { target: { value: "admin" } });
    fireEvent.keyDown(input, { key: "," });
    expect(tags()).toBe("lager,bericht,admin");
    fireEvent.change(input, { target: { value: "neu" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(tags()).toBe("lager,bericht,admin,neu");

    fireEvent.keyDown(input, { key: "Backspace" });
    expect(tags()).toBe("lager,bericht,admin");
  });
});
