"use client";

import { useEffect, useRef } from "react";
import { useLocale } from "next-intl";

import { loadFriendlyChallenge, mountFriendlyCaptcha } from "@/lib/friendly-captcha";

type Props = {
  sitekey: string;
  puzzleEndpoint?: string;
  onSolved: (solution: string) => void;
  onExpired?: () => void;
};

// Jede Montage erzeugt ein eigenes FriendlyCaptcha-Widget (siehe lib/friendly-captcha.ts): das
// Vendor-Skript initialisiert nur beim Laden, ein spaeter (Client-Navigation, Neustart ueber `key`)
// gemountetes Element bekaeme sonst nie eine Challenge.
export function CaptchaWidget({ sitekey, puzzleEndpoint, onSolved, onExpired }: Props) {
  const locale = useLocale();
  const containerRef = useRef<HTMLDivElement>(null);
  // Callbacks per Ref, damit ein neuer Callback (andere Render-Identitaet) das laufende Widget
  // nicht zerstoert und eine bereits begonnene Challenge neu startet.
  const onSolvedRef = useRef(onSolved);
  const onExpiredRef = useRef(onExpired);
  useEffect(() => {
    onSolvedRef.current = onSolved;
    onExpiredRef.current = onExpired;
  }, [onSolved, onExpired]);

  useEffect(() => {
    const container = containerRef.current;
    if (!sitekey || !container) return;
    let disposed = false;
    let unmount: (() => void) | null = null;

    loadFriendlyChallenge()
      .then((api) => {
        if (disposed) return;
        unmount = mountFriendlyCaptcha(container, api, {
          sitekey,
          language: locale,
          puzzleEndpoint,
          onSolved: (solution) => onSolvedRef.current(solution),
          // Puzzle konnte nicht geholt werden o. ae. - das Widget zeigt selbst einen
          // Neustart-Button; eine eventuell gemerkte Loesung gilt nicht mehr.
          onError: () => onExpiredRef.current?.(),
        });
      })
      .catch((error: unknown) => {
        // Skript nicht ladbar (Netzwerk/Blocker): Status bleibt auf "Sicherheitscheck laeuft",
        // ein Neustart der Seite bzw. ein Remount laedt erneut.
        console.error("[abgabebox] FriendlyCaptcha konnte nicht geladen werden", error);
      });

    return () => {
      disposed = true;
      unmount?.();
    };
  }, [sitekey, locale, puzzleEndpoint]);

  if (!sitekey) return null;

  return <div ref={containerRef} />;
}
