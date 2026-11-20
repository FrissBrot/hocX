"use client";

import { KeyboardEvent, ReactNode, useRef } from "react";

/** Tastatur für eine Gruppe aus `role="radio"`-Elementen (WAI-ARIA Radio Group): nur das gewählte
 * Element ist per Tab erreichbar, Pfeiltasten/Pos1/Ende wählen und fokussieren das nächste
 * aktive Element. Auch für Karten- oder Chip-Gruppen, die nicht als Segment aussehen. */
export function useRadioGroupKeys(count: number, selectedIndex: number, onSelect: (index: number) => void, isDisabled: (index: number) => boolean = () => false) {
  const refs = useRef<(HTMLElement | null)[]>([]);
  const enabled = Array.from({ length: count }, (_, index) => index).filter((index) => !isDisabled(index));
  const tabStop = selectedIndex >= 0 && !isDisabled(selectedIndex) ? selectedIndex : enabled[0];

  function onKeyDown(event: KeyboardEvent<HTMLElement>, index: number) {
    // Wie rovingKeyDown (lib/a11y/roving.ts): Kombinationen (Alt+Pfeil = Reihenfolge, Strg …) und
    // bereits behandelte Tasten gehören nicht der Gruppe
    if (enabled.length === 0 || event.altKey || event.ctrlKey || event.metaKey || event.defaultPrevented) return;
    const position = enabled.indexOf(index);
    let next: number | undefined;
    if (event.key === "ArrowRight" || event.key === "ArrowDown") next = enabled[(position + 1) % enabled.length];
    else if (event.key === "ArrowLeft" || event.key === "ArrowUp") next = enabled[(position - 1 + enabled.length) % enabled.length];
    else if (event.key === "Home") next = enabled[0];
    else if (event.key === "End") next = enabled[enabled.length - 1];
    if (next === undefined) return;
    event.preventDefault();
    refs.current[next]?.focus();
    onSelect(next);
  }

  return (index: number) => ({
    ref: (element: HTMLElement | null) => {
      refs.current[index] = element;
    },
    tabIndex: index === tabStop ? 0 : -1,
    onKeyDown: (event: KeyboardEvent<HTMLElement>) => onKeyDown(event, index),
  });
}

export type SegmentOption<T extends string> = {
  value: T;
  label: ReactNode;
  disabled?: boolean;
  /** z. B. Hilfetext, warum die Option deaktiviert ist */
  describedBy?: string;
};

type Props<T extends string> = {
  options: SegmentOption<T>[];
  value: T;
  onChange: (value: T) => void;
  "aria-label"?: string;
  "aria-labelledby"?: string;
  className?: string;
};

/** Umschalter für wenige, gleichrangige Werte (Segment): eine Auswahl, per Tastatur wie eine
 * Radio-Gruppe. Lange Listen bleiben bei `Select`/`SearchableSelect` (DESIGN.md Abschnitt 5). */
export function SegmentedControl<T extends string>({ options, value, onChange, className, ...aria }: Props<T>) {
  const itemProps = useRadioGroupKeys(
    options.length,
    options.findIndex((option) => option.value === value),
    (index) => onChange(options[index].value),
    (index) => Boolean(options[index].disabled)
  );
  return (
    <div role="radiogroup" className={className ? `segmented-control ${className}` : "segmented-control"} {...aria}>
      {options.map((option, index) => {
        const { ref, ...keys } = itemProps(index);
        return (
          <button
            key={option.value}
            ref={ref}
            type="button"
            role="radio"
            className="segmented-control-option"
            aria-checked={option.value === value}
            aria-describedby={option.describedBy}
            disabled={option.disabled}
            onClick={() => onChange(option.value)}
            {...keys}
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
}
