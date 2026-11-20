import type { ReactNode } from "react";

export type FilterTabOption<T extends string = string> = {
  value: T;
  label: string;
  count?: number;
  /** Optionales Icon vor dem Text (z. B. Ansicht Liste/Board). */
  icon?: ReactNode;
  /** Nicht wählbar (z. B. «Extrahierter Text», solange es keinen Text gibt). */
  disabled?: boolean;
  /** Tooltip, z. B. warum die Option nicht wählbar ist. */
  title?: string;
};

type Props<T extends string> = {
  options: FilterTabOption<T>[];
  value: T;
  onChange: (value: T) => void;
  /** "chips": einzelne Pills mit Rahmen statt der grauen Schiene (z.B. Plan-Filter). */
  variant?: "segmented" | "chips";
};

export function FilterTabs<T extends string>({ options, value, onChange, variant = "segmented" }: Props<T>) {
  return (
    <div className={variant === "chips" ? "filter-tabs filter-tabs-chips" : "filter-tabs"} role="tablist">
      {options.map((option) => {
        const isActive = option.value === value;
        return (
          <button
            key={option.value}
            type="button"
            role="tab"
            aria-selected={isActive}
            disabled={option.disabled}
            title={option.title}
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
