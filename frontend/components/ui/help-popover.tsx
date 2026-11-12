"use client";

import { ReactNode, useId, useRef, useState, useSyncExternalStore } from "react";
import { createPortal } from "react-dom";
import { useTranslations } from "next-intl";

import { DocsPage, docsUrl } from "@/lib/docs";
import { usePopoverDismiss, usePopoverPosition } from "./popover";

const noSubscribe = () => () => {};

/**
 * Doku-Adresse erst nach der Hydration: die Doku-Domain steht nur im Browser
 * (`window.__HOCX_CONFIG__`), der Server rendert deshalb ohne Link. Über den Server-Snapshot
 * stimmt das erste Client-Rendering mit dem Server-HTML überein (sonst Hydration-Fehler).
 */
function useDocsUrl(page: DocsPage | undefined, anchor?: string): string | null {
  return useSyncExternalStore(noSubscribe, () => (page ? docsUrl(page, anchor) : null), () => null);
}

type HelpPopoverProps = {
  /** Wofür die Hilfe ist, für Screenreader («Hilfe zu …»). */
  topic: string;
  /** Kurze Erklärung, 1–3 Sätze. */
  children: ReactNode;
  /** Optional: Abschnitt der Benutzer-Doku. Ohne Doku-Domain erscheint kein Link. */
  docs?: { page: DocsPage; anchor?: string };
};

/**
 * Kleiner «?»-Knopf neben einem Feldlabel. Öffnet eine kurze Erklärung und, falls konfiguriert,
 * einen Link in die Benutzer-Doku. Für Hilfe, die nicht dauernd sichtbar sein muss; dauernde
 * Hinweise bleiben `field-help`.
 */
export function HelpPopover({ topic, children, docs }: HelpPopoverProps) {
  const t = useTranslations("common.help");
  const [open, setOpen] = useState(false);
  const anchorRef = useRef<HTMLButtonElement | null>(null);
  const panelRef = useRef<HTMLDivElement | null>(null);
  const style = usePopoverPosition(open, anchorRef, "start", 6, { minWidth: 260, estimatedHeight: 180 });
  usePopoverDismiss(open, () => setOpen(false), [anchorRef, panelRef]);
  const panelId = useId();
  const href = useDocsUrl(docs?.page, docs?.anchor);

  return (
    <>
      <button
        ref={anchorRef}
        type="button"
        className="help-popover-trigger"
        aria-label={t("about", { topic })}
        aria-expanded={open}
        aria-controls={open ? panelId : undefined}
        onClick={() => setOpen((value) => !value)}
      >
        ?
      </button>
      {open && typeof document !== "undefined"
        ? createPortal(
            <div ref={panelRef} id={panelId} role="dialog" aria-label={t("about", { topic })} className="popover-panel help-popover-panel" style={style}>
              <div className="help-popover-text">{children}</div>
              {href ? (
                <a className="help-popover-link" href={href} target="_blank" rel="noopener noreferrer">
                  {t("moreInDocs")}
                </a>
              ) : null}
            </div>,
            document.body
          )
        : null}
    </>
  );
}

/** Link in die Benutzer-Doku (neuer Tab); ohne konfigurierte Doku-Domain nichts. */
export function DocsLink({ page, anchor, children }: { page: DocsPage; anchor?: string; children: ReactNode }) {
  const href = useDocsUrl(page, anchor);
  if (!href) return null;
  return (
    <a className="docs-link" href={href} target="_blank" rel="noopener noreferrer">
      {children}
    </a>
  );
}
