import { InputHTMLAttributes, forwardRef } from "react";

type Props = {
  value: string;
  onChange: (value: string) => void;
} & Omit<InputHTMLAttributes<HTMLInputElement>, "value" | "onChange" | "type">;

export const SearchInput = forwardRef<HTMLInputElement, Props>(function SearchInput(
  { value, onChange, className, placeholder, ...rest },
  ref
) {
  return (
    <div className={`search-input${className ? ` ${className}` : ""}`}>
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
    </div>
  );
});
