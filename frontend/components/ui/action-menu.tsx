"use client";

import { Fragment, ReactNode, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { menuButtonKeyDown, Popover } from "./popover";

export type ActionMenuItem = {
  label: string;
  onClick: () => void;
  danger?: boolean;
  /** Trennlinie vor diesem Eintrag (z. B. vor «Löschen»). */
  separatorBefore?: boolean;
  /** Vorübergehend nicht wählbar (z. B. PDF wird gerade erzeugt). */
  disabled?: boolean;
};

export function ActionMenu({
  items,
  ariaLabel,
  icon,
  triggerClassName = "button-ghost button-icon",
}: {
  items: ActionMenuItem[];
  ariaLabel?: string;
  /** Eigenes Symbol statt «⋮» (z. B. Export im Protokoll-Kopf). */
  icon?: ReactNode;
  triggerClassName?: string;
}) {
  const t = useTranslations("common");
  const resolvedAriaLabel = ariaLabel ?? t("actions");
  const [open, setOpen] = useState(false);
  const wrapRef = useRef<HTMLDivElement>(null);

  return (
    <div className="action-menu-wrap" ref={wrapRef} onClick={(event) => event.stopPropagation()}>
      <button
        type="button"
        className={triggerClassName}
        title={resolvedAriaLabel}
        aria-label={resolvedAriaLabel}
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        onKeyDown={menuButtonKeyDown(open, setOpen)}
      >
        <span aria-hidden="true">{icon ?? "⋮"}</span>
      </button>
      <Popover open={open} onOpenChange={setOpen} anchorRef={wrapRef} align="end" className="action-menu" label={resolvedAriaLabel}>
        <>
          {items.map((item) => (
            <Fragment key={item.label}>
            {item.separatorBefore ? <div className="action-menu-separator" role="separator" /> : null}
            <button
              type="button"
              role="menuitem"
              className={item.danger ? "action-menu-item action-menu-item-danger" : "action-menu-item"}
              disabled={item.disabled}
              onClick={() => {
                setOpen(false);
                item.onClick();
              }}
            >
              {item.label}
            </button>
            </Fragment>
          ))}
        </>
      </Popover>
    </div>
  );
}
