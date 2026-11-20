import { InputHTMLAttributes, forwardRef } from "react";

type Props = {
  value: string;
  onChange: (value: string) => void;
  /** Beschriftung des runden ×-Knopfs zum Leeren; ohne sie gibt es keinen Knopf. */
  clearLabel?: string;
} & Omit<InputHTMLAttributes<HTMLInputElement>, "value" | "onChange" | "type">;

export const SearchInput = forwardRef<HTMLInputElement, Props>(function SearchInput(
  { value, onChange, className, placeholder, clearLabel, ...rest },
  ref
) {
  const clearable = Boolean(clearLabel) && value !== "";
  return (
    <div className={`search-input${clearable ? " search-input-clearable" : ""}${className ? ` ${className}` : ""}`}>
      <svg className="search-input-icon" width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">
        <circle cx="7" cy="7" r="5.25" stroke="currentColor" strokeWidth="1.5" />
        <path d="M11 11L14.5 14.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
      </svg>
      <input
        ref={ref}
        type="text"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
        {...rest}
      />
      {clearable ? (
        <button type="button" className="search-input-clear" aria-label={clearLabel} onClick={() => onChange("")}>
          <svg width="10" height="10" viewBox="0 0 10 10" fill="none" aria-hidden="true">
            <path d="M2 2l6 6M8 2L2 8" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
          </svg>
        </button>
      ) : null}
    </div>
  );
});
