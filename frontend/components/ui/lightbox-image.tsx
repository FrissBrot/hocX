"use client";

import { useEffect, useState } from "react";
import { createPortal } from "react-dom";

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
  const [open, setOpen] = useState(false);

  useEffect(() => {
    if (!open) return;
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") setOpen(false);
    }
    window.addEventListener("keydown", onKey);
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = "";
    };
  }, [open]);

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
            <div className="image-lightbox-backdrop" onClick={() => setOpen(false)} role="presentation">
              <img alt={alt} src={src} className="image-lightbox-img" onClick={(event) => event.stopPropagation()} />
              <button
                type="button"
                className="image-lightbox-close"
                onClick={() => setOpen(false)}
                aria-label="Schliessen"
              >
                <svg width="18" height="18" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
                  <line x1="3" y1="3" x2="13" y2="13" />
                  <line x1="13" y1="3" x2="3" y2="13" />
                </svg>
              </button>
            </div>,
            document.body
          )
        : null}
    </>
  );
}
