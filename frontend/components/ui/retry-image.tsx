"use client";

import type { ImgHTMLAttributes, ReactNode } from "react";

import { useImageRetry } from "@/lib/hooks/use-image-retry";

type Props = Omit<ImgHTMLAttributes<HTMLImageElement>, "src" | "onError"> & {
  src: string;
  /** Erst nach allen gescheiterten Versuchen gezeigt (Standard: nichts). */
  fallback?: ReactNode;
};

/** Vorschaubild, das vorübergehende Fehler (503/429, Abbruch) selbst begrenzt wiederholt, siehe
 * useImageRetry. Zwischen zwei Versuchen bleibt die Fläche leer (gleiche Grösse, kein kaputtes
 * Bildsymbol); den Platzhalter zeigt erst der letzte Fehlschlag. */
export function RetryImage({ src, fallback = null, className, alt = "", ...rest }: Props) {
  const image = useImageRetry(src);
  if (image.failed || !image.src) return <>{fallback}</>;
  const classes = [className, image.waiting ? "image-retry-pending" : null].filter(Boolean).join(" ");
  return (
    // eslint-disable-next-line @next/next/no-img-element -- Vorschau kommt authentifiziert von der API bzw. vom öffentlichen Link-Endpunkt
    <img {...rest} alt={alt} src={image.src} className={classes || undefined} onError={image.onError} />
  );
}
