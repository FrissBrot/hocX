export type FilterTabOption<T extends string = string> = {
  value: T;
  label: string;
  count?: number;
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
            className={`filter-tabs-option${isActive ? " filter-tabs-option-active" : ""}`}
            onClick={() => onChange(option.value)}
          >
            {option.label}
            {option.count !== undefined ? <span className="filter-tabs-count">{option.count}</span> : null}
          </button>
        );
      })}
    </div>
  );
}
