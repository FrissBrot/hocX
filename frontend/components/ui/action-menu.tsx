"use client";

import { useRef, useState } from "react";
import { Popover } from "./popover";

export type ActionMenuItem = {
  label: string;
  onClick: () => void;
  danger?: boolean;
};

export function ActionMenu({ items, ariaLabel = "Aktionen" }: { items: ActionMenuItem[]; ariaLabel?: string }) {
  const [open, setOpen] = useState(false);
  const wrapRef = useRef<HTMLDivElement>(null);

  return (
    <div className="action-menu-wrap" ref={wrapRef} onClick={(event) => event.stopPropagation()}>
      <button type="button" className="button-ghost button-icon" title={ariaLabel} aria-label={ariaLabel} onClick={() => setOpen((v) => !v)}>
        ⋮
      </button>
      <Popover open={open} onOpenChange={setOpen} anchorRef={wrapRef} align="end" className="action-menu">
        <>
          {items.map((item) => (
            <button
              key={item.label}
              type="button"
              role="menuitem"
              className={item.danger ? "action-menu-item action-menu-item-danger" : "action-menu-item"}
              onClick={() => {
                setOpen(false);
                item.onClick();
              }}
            >
              {item.label}
            </button>
          ))}
        </>
      </Popover>
    </div>
  );
}
