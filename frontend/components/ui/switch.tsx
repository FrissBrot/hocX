"use client";

import { ReactNode, useId } from "react";

type Props = {
  checked: boolean;
  onChange: (checked: boolean) => void;
  label: ReactNode;
  /** Erklärung unter dem Label (wird als Beschreibung vorgelesen) */
  help?: ReactNode;
  disabled?: boolean;
  className?: string;
};

/** Ein/Aus-Schalter mit Label und Hilfetext. Technisch eine Checkbox mit `role="switch"`, daher
 * Leertaste und Klick auf den ganzen Text wie gewohnt. */
export function Switch({ checked, onChange, label, help, disabled, className }: Props) {
  const id = useId();
  const labelId = `${id}-label`;
  const helpId = `${id}-help`;
  return (
    <label className={className ? `switch-row ${className}` : "switch-row"}>
      <input
        type="checkbox"
        role="switch"
        className="switch-input"
        checked={checked}
        disabled={disabled}
        // Name nur aus dem Label, der Hilfetext ist die Beschreibung (sonst läse sich beides als Name)
        aria-labelledby={labelId}
        aria-describedby={help ? helpId : undefined}
        onChange={(event) => onChange(event.target.checked)}
      />
      <span className="switch-track" aria-hidden="true" />
      <span className="switch-text">
        <span className="switch-label" id={labelId}>{label}</span>
        {help ? <span className="switch-help" id={helpId}>{help}</span> : null}
      </span>
    </label>
  );
}
