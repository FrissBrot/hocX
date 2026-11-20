"use client";

import type { ReactNode } from "react";

import { rovingKeyDown } from "@/lib/a11y/roving";

export type FilterTabOption<T extends string = string> = {
  value: T;
  label: string;
  count?: number;
  /** Optionales Icon vor dem Text (z. B. Ansicht Liste/Board). */
  icon?: ReactNode;
};

type Props<T extends string> = {
  options: FilterTabOption<T>[];
  value: T;
  onChange: (value: T) => void;
  /** "chips": einzelne Pills mit Rahmen statt der grauen Schiene (z.B. Plan-Filter). */
  variant?: "segmented" | "chips";
};

export function FilterTabs<T extends string>({ options, value, onChange, variant = "segmented" }: Props<T>) {
  // Gibt es den Wert nicht (mehr), ist der erste Eintrag der Tab-Halt
  const focusValue = options.some((option) => option.value === value) ? value : options[0]?.value;
  return (
    // Filter-Schiene als Tabs ohne eigenes Panel: ein Tab-Halt, Pfeile wählen den Filter sofort
    <div
      className={variant === "chips" ? "filter-tabs filter-tabs-chips" : "filter-tabs"}
      role="tablist"
      onKeyDown={(event) =>
        rovingKeyDown(event, {
          itemSelector: '[role="tab"]',
          onMove: (element) => {
            const next = options.find((option) => option.value === element.dataset.value);
            if (next) onChange(next.value);
          },
        })
      }
    >
      {options.map((option) => {
        const isActive = option.value === value;
        return (
          <button
            key={option.value}
            type="button"
            role="tab"
            data-value={option.value}
            aria-selected={isActive}
            tabIndex={option.value === focusValue ? 0 : -1}
            className={`filter-tabs-option${isActive ? " filter-tabs-option-active" : ""}`}
            onClick={() => onChange(option.value)}
          >
            {option.icon}
            {option.label}
            {option.count !== undefined ? <span className="filter-tabs-count">{option.count}</span> : null}
          </button>
        );
      })}
    </div>
  );
}
