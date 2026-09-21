"use client";

import { useEffect, useRef, useState } from "react";

// Wer nur mit der Maus durch das Raster fährt, soll nicht für jede überstrichene Kachel ein
// Video laden: erst wenn `active` so lange anliegt, wird der Clip angefordert.
const LIVE_CLIP_REQUEST_DELAY_MS = 150;

/**
 * Der Clip eines Live Photos (kurzes, stummes MP4), das über dem Standbild abgespielt wird,
 * solange `active` gilt. Bis das erste Videobild da ist, bleibt das Standbild sichtbar (kein
 * schwarzer Blitz); danach wird er ausgeblendet und auf Anfang zurückgesetzt. Bei
 * `prefers-reduced-motion` wird nie abgespielt.
 */
export function LivePhotoClip({ src, active, className }: { src: string; active: boolean; className: string }) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [requested, setRequested] = useState(false);
  const [playing, setPlaying] = useState(false);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    if (!active || requested) return;
    const timer = setTimeout(() => setRequested(true), LIVE_CLIP_REQUEST_DELAY_MS);
    return () => clearTimeout(timer);
  }, [active, requested]);

  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;
    if (active && !window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) {
      // play() wird abgelehnt, wenn der Nutzer den Zeiger schon wieder weggezogen hat und
      // pause() dazwischenkam - kein Fehler, der Clip soll dann einfach nicht laufen.
      video.play()?.catch(() => {});
    } else {
      video.pause();
      video.currentTime = 0;
      setPlaying(false);
    }
  }, [active, requested]);

  if (!requested || failed) return null;

  return (
    <video
      ref={videoRef}
      src={src}
      className={`${className}${playing ? ` ${className}-playing` : ""}`}
      muted
      loop
      playsInline
      preload="auto"
      aria-hidden="true"
      tabIndex={-1}
      onPlaying={() => setPlaying(true)}
      onError={() => setFailed(true)}
    />
  );
}
