"use client";

import { useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useTranslations } from "next-intl";
import { ActionIcon } from "@/components/ui/action-icons";

import { usePopupEscape, usePopupScrollLock } from "@/lib/hooks/use-popup-escape";
import { useModalFocus } from "@/lib/a11y/use-focus-trap";

type LightboxImageProps = {
  src: string;
  alt: string;
  className?: string;
  /** Smaller preview shown in the trigger thumbnail, e.g. a generated thumbnail - the
   * lightbox popup always opens with the full-resolution `src`. Falls back to `src` when
   * omitted. */
  previewSrc?: string;
};

export function LightboxImage({ src, alt, className, previewSrc }: LightboxImageProps) {
  const tCommon = useTranslations("common");
  const [open, setOpen] = useState(false);

  const rootRef = useRef<HTMLDivElement>(null);
  usePopupEscape(open, () => setOpen(false), rootRef);
  usePopupScrollLock(open);
  // Vollbild-Ansicht ist ein modaler Dialog: Fokus hinein, Tab bleibt drin, danach zurück aufs Bild
  useModalFocus(open, rootRef);

  return (
    <>
      <img
        alt={alt}
        src={previewSrc ?? src}
        loading="lazy"
        decoding="async"
        className={className ? `${className} image-lightbox-trigger` : "image-lightbox-trigger"}
        onClick={() => setOpen(true)}
        role="button"
        tabIndex={0}
        onKeyDown={(event) => {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            setOpen(true);
          }
        }}
      />
      {open && typeof document !== "undefined"
        ? createPortal(
            <div ref={rootRef} className="image-lightbox-backdrop" onClick={() => setOpen(false)} /* a11y-ok: Klick auf den Hintergrund schliesst, Tastatur: Escape/Schliessen-Knopf */ role="dialog" aria-modal="true" aria-label={alt || tCommon("close")} tabIndex={-1}>
              <img alt={alt} src={src} className="image-lightbox-img" onClick={(event) => event.stopPropagation()} />
              <button
                type="button"
                className="image-lightbox-close"
                onClick={() => setOpen(false)}
                aria-label={tCommon("close")}
              >
                <ActionIcon name="close" width={18} height={18} />
              </button>
            </div>,
            document.body
          )
        : null}
    </>
  );
}
