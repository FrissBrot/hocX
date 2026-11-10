"use client";

// Farbfeld im hocX-Look statt <input type="color"> (dessen Dialog kommt vom Betriebssystem).
// Ein Farbfeld-Button öffnet ein Popover mit Sättigungs-/Helligkeitsfläche, Farbton-Regler (beide
// per Maus und Tastatur), Hex-Eingabe und Farbfeldern (eigene `swatches`, sonst eine Palette).
// Wert immer «#RRGGBB» in Grossbuchstaben; onChange läuft wie beim nativen Feld schon beim Ziehen.

import { KeyboardEvent, PointerEvent, RefObject, useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { createPortal } from "react-dom";

import { usePopoverDismiss, usePopoverPosition } from "./popover";

const HEX = /^#([0-9a-f]{6})$/i;

// Vorschläge ohne eigene Farbfelder: Farbwerte sind Daten der Dokumente, keine UI-Farben
const PALETTE = [
  "#1F2937", "#4B5563", "#9CA3AF", "#FFFFFF", // design-ok: Farbvorschläge (Daten)
  "#B91C1C", "#C2410C", "#B45309", "#4D7C0F", // design-ok: Farbvorschläge (Daten)
  "#047857", "#0E7490", "#1D4ED8", "#4338CA", // design-ok: Farbvorschläge (Daten)
  "#6D28D9", "#A21CAF", "#BE185D", "#7A1F2B", // design-ok: Farbvorschläge (Daten)
];

type Hsv = { h: number; s: number; v: number };

export function normalizeHex(value: string | null | undefined): string | null {
  const text = (value ?? "").trim();
  const withHash = text.startsWith("#") ? text : `#${text}`;
  if (/^#[0-9a-f]{3}$/i.test(withHash)) {
    return `#${withHash.slice(1).split("").map((char) => char + char).join("")}`.toUpperCase();
  }
  return HEX.test(withHash) ? withHash.toUpperCase() : null;
}

function hexToHsv(hex: string): Hsv {
  const value = Number.parseInt(hex.slice(1), 16);
  const r = ((value >> 16) & 255) / 255;
  const g = ((value >> 8) & 255) / 255;
  const b = (value & 255) / 255;
  const max = Math.max(r, g, b);
  const delta = max - Math.min(r, g, b);
  let h = 0;
  if (delta) {
    if (max === r) h = ((g - b) / delta) % 6;
    else if (max === g) h = (b - r) / delta + 2;
    else h = (r - g) / delta + 4;
  }
  return { h: (h * 60 + 360) % 360, s: max ? delta / max : 0, v: max };
}

function hsvToHex({ h, s, v }: Hsv): string {
  const channel = (n: number) => {
    const k = (n + h / 60) % 6;
    return Math.round((v - v * s * Math.max(0, Math.min(k, 4 - k, 1))) * 255);
  };
  return `#${[channel(5), channel(3), channel(1)].map((part) => part.toString(16).padStart(2, "0")).join("")}`.toUpperCase();
}

const clamp = (value: number) => Math.min(1, Math.max(0, value));

type Props = {
  value: string | null | undefined;
  onChange: (value: string) => void;
  "aria-label"?: string;
  id?: string;
  disabled?: boolean;
  /** Farbfelder, z. B. die Farben des Brand-Profils */
  swatches?: { value: string; label: string }[];
  className?: string;
};

export function ColorInput({ value, onChange, "aria-label": ariaLabel, id, disabled, swatches, className }: Props) {
  const t = useTranslations("common");
  const [open, setOpen] = useState(false);
  const buttonRef = useRef<HTMLButtonElement | null>(null);
  const hex = normalizeHex(value) ?? "#000000"; // design-ok: Ersatzwert eines leeren Farbfelds (Daten)
  return (
    <>
      <button
        ref={buttonRef}
        id={id}
        type="button"
        className={`color-input${className ? ` ${className}` : ""}`}
        aria-label={ariaLabel}
        title={hex}
        aria-haspopup="dialog"
        aria-expanded={open}
        disabled={disabled}
        onClick={() => setOpen((current) => !current)}
      >
        <span className="color-input-swatch" style={{ background: hex }} aria-hidden="true" />
      </button>
      {open && (
        <ColorPopover
          anchorRef={buttonRef}
          value={hex}
          label={ariaLabel ?? t("colorField.choose")}
          swatches={swatches ?? PALETTE.map((item) => ({ value: item, label: item }))}
          onChange={onChange}
          onClose={(keyboard) => {
            setOpen(false);
            if (keyboard) buttonRef.current?.focus();
          }}
        />
      )}
    </>
  );
}

function ColorPopover({
  anchorRef,
  value,
  label,
  swatches,
  onChange,
  onClose,
}: {
  anchorRef: RefObject<HTMLButtonElement | null>;
  value: string;
  label: string;
  swatches: { value: string; label: string }[];
  onChange: (value: string) => void;
  onClose: (keyboard: boolean) => void;
}) {
  const t = useTranslations("common");
  const panelRef = useRef<HTMLDivElement | null>(null);
  const areaRef = useRef<HTMLDivElement | null>(null);
  const hueRef = useRef<HTMLDivElement | null>(null);
  const style = usePopoverPosition(true, anchorRef, "start", 6, { minWidth: 248, estimatedHeight: 340 });
  const close = () => onClose(panelRef.current?.contains(document.activeElement) ?? false);
  usePopoverDismiss(true, close, [anchorRef, panelRef]);
  // Farbton bleibt bei Grau/Schwarz erhalten (aus dem Hex-Wert nicht ableitbar)
  const [hsv, setHsv] = useState<Hsv>(() => hexToHsv(value));
  const [text, setText] = useState(value);

  // Beim Ziehen liest der Zeiger-Handler den jeweils aktuellen Stand, nicht den beim Drücken
  const hsvRef = useRef(hsv);
  hsvRef.current = hsv;

  // Neuer Wert von aussen (z. B. Zurücksetzen): übernehmen, Farbton bei Grau behalten
  useEffect(() => {
    setText(value);
    if (hsvToHex(hsvRef.current) === value) return;
    const next = hexToHsv(value);
    setHsv(next.s ? next : { ...next, h: hsvRef.current.h });
  }, [value]);

  function apply(next: Hsv) {
    hsvRef.current = next;
    setHsv(next);
    onChange(hsvToHex(next));
  }

  function drag(onMove: (x: number, y: number) => void) {
    return (event: PointerEvent<HTMLDivElement>) => {
      const element = event.currentTarget;
      event.preventDefault();
      element.focus();
      const update = (clientX: number, clientY: number) => {
        const rect = element.getBoundingClientRect();
        onMove(clamp((clientX - rect.left) / (rect.width || 1)), clamp((clientY - rect.top) / (rect.height || 1)));
      };
      update(event.clientX, event.clientY);
      element.setPointerCapture?.(event.pointerId);
      const move = (moveEvent: globalThis.PointerEvent) => update(moveEvent.clientX, moveEvent.clientY);
      const stop = () => {
        element.removeEventListener("pointermove", move);
        element.removeEventListener("pointerup", stop);
      };
      element.addEventListener("pointermove", move);
      element.addEventListener("pointerup", stop);
    };
  }

  function onAreaKey(event: KeyboardEvent<HTMLDivElement>) {
    const stepSize = event.shiftKey ? 0.1 : 0.01;
    const moves: Record<string, Partial<Hsv>> = {
      ArrowLeft: { s: clamp(hsv.s - stepSize) },
      ArrowRight: { s: clamp(hsv.s + stepSize) },
      ArrowUp: { v: clamp(hsv.v + stepSize) },
      ArrowDown: { v: clamp(hsv.v - stepSize) },
    };
    if (moves[event.key]) {
      event.preventDefault();
      apply({ ...hsv, ...moves[event.key] });
    }
  }

  function onHueKey(event: KeyboardEvent<HTMLDivElement>) {
    const stepSize = event.shiftKey ? 15 : 1;
    const moves: Record<string, number> = { ArrowLeft: -stepSize, ArrowDown: -stepSize, ArrowRight: stepSize, ArrowUp: stepSize };
    if (event.key in moves) {
      event.preventDefault();
      apply({ ...hsv, h: Math.min(359, Math.max(0, hsv.h + moves[event.key])) });
    }
  }

  if (typeof document === "undefined") return null;
  return createPortal(
    <div ref={panelRef} className="popover-panel color-picker" style={style} role="dialog" aria-label={label}>
      <div
        ref={areaRef}
        className="color-picker-area"
        // Laufzeitfarbe: Grundfarbton der Fläche
        style={{ backgroundColor: `hsl(${hsv.h} 100% 50%)` }}
        role="slider"
        tabIndex={0}
        aria-label={t("colorField.saturationBrightness")}
        aria-valuetext={t("colorField.saturationBrightnessValue", { saturation: Math.round(hsv.s * 100), brightness: Math.round(hsv.v * 100) })}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(hsv.s * 100)}
        onPointerDown={drag((x, y) => apply({ ...hsvRef.current, s: x, v: 1 - y }))}
        onKeyDown={onAreaKey}
      >
        <span className="color-picker-thumb" style={{ left: `${hsv.s * 100}%`, top: `${(1 - hsv.v) * 100}%`, background: hsvToHex(hsv) }} aria-hidden="true" />
      </div>
      <div
        ref={hueRef}
        className="color-picker-hue"
        role="slider"
        tabIndex={0}
        aria-label={t("colorField.hue")}
        aria-valuemin={0}
        aria-valuemax={359}
        aria-valuenow={Math.round(hsv.h)}
        onPointerDown={drag((x) => apply({ ...hsvRef.current, h: Math.min(359, x * 360) }))}
        onKeyDown={onHueKey}
      >
        <span className="color-picker-hue-thumb" style={{ left: `${(hsv.h / 360) * 100}%` }} aria-hidden="true" />
      </div>
      <label className="color-picker-hex">
        <span className="field-label">{t("colorField.hex")}</span>
        <input
          className="color-picker-hex-input"
          value={text}
          maxLength={7}
          spellCheck={false}
          onChange={(event) => {
            setText(event.target.value);
            const normalized = normalizeHex(event.target.value);
            if (normalized && normalized.length === 7 && event.target.value.replace("#", "").length === 6) {
              setHsv(hexToHsv(normalized));
              onChange(normalized);
            }
          }}
          onBlur={() => {
            const normalized = normalizeHex(text);
            if (normalized) {
              setHsv(hexToHsv(normalized));
              setText(normalized);
              onChange(normalized);
            } else {
              setText(value);
            }
          }}
        />
      </label>
      <div className="color-picker-swatches" role="group" aria-label={t("colorField.swatches")}>
        {swatches.filter((swatch) => normalizeHex(swatch.value)).map((swatch) => (
          <button
            key={`${swatch.label}-${swatch.value}`}
            type="button"
            className={normalizeHex(swatch.value) === value ? "color-picker-swatch color-picker-swatch-active" : "color-picker-swatch"}
            style={{ background: swatch.value }}
            aria-label={swatch.label}
            title={swatch.label}
            aria-pressed={normalizeHex(swatch.value) === value}
            onClick={() => {
              const normalized = normalizeHex(swatch.value);
              if (!normalized) return;
              setHsv(hexToHsv(normalized));
              onChange(normalized);
            }}
          />
        ))}
      </div>
    </div>,
    document.body
  );
}
