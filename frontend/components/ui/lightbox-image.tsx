"use client";

import { useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useTranslations } from "next-intl";
import { ActionIcon } from "@/components/ui/action-icons";

import { usePopupEscape, usePopupScrollLock } from "@/lib/hooks/use-popup-escape";

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
            <div ref={rootRef} className="image-lightbox-backdrop" onClick={() => setOpen(false)} role="presentation">
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
