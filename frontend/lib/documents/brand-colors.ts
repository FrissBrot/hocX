// Ableitung der Brand-Farben aus Haupt- und Zweitfarbe (Brand Studio, Modus «automatisch»).
// Alle Werte sind Daten für das PDF, keine UI-Farben: deshalb Hex statt Design-Tokens.

const WHITE = "#FFFFFF"; // design-ok: Dokumentfarbe (Daten)
const BLACK = "#000000"; // design-ok: Dokumentfarbe (Daten)
const NEUTRAL_MUTED = "#6B7280"; // design-ok: Dokumentfarbe (Daten)
const NEUTRAL_BORDER = "#D0D5DD"; // design-ok: Dokumentfarbe (Daten)

function channels(hex: string): [number, number, number] {
  const value = /^#?([0-9a-f]{6})$/i.exec(hex.trim())?.[1] ?? "000000";
  return [0, 2, 4].map((offset) => parseInt(value.slice(offset, offset + 2), 16)) as [number, number, number];
}

/** Mischt ``amount`` (0..1) von ``other`` in ``base``. */
export function mixColor(base: string, other: string, amount: number): string {
  const a = channels(base);
  const b = channels(other);
  return `#${a.map((channel, index) => Math.round(channel + (b[index] - channel) * amount).toString(16).padStart(2, "0")).join("").toUpperCase()}`;
}

/** Farben, die das Brand Studio aus Haupt- und Zweitfarbe ableitet. Statusfarben
 *  (Erfolg, Warnung, Gefahr, Information) bleiben unverändert, sie tragen eine feste Bedeutung. */
export function deriveBrandColors(primary: string, secondary: string): Record<string, string> {
  const text = mixColor(primary, BLACK, 0.82);
  return {
    accent: secondary.toUpperCase(),
    accent_2: mixColor(primary, secondary, 0.5),
    heading: primary.toUpperCase(),
    text,
    muted: mixColor(NEUTRAL_MUTED, primary, 0.15),
    background: WHITE,
    surface: mixColor(WHITE, primary, 0.04),
    border: mixColor(NEUTRAL_BORDER, primary, 0.1),
    watermark: mixColor(WHITE, primary, 0.06),
    table_header_background: mixColor(WHITE, primary, 0.1),
    table_header_text: mixColor(primary, BLACK, 0.35),
    table_zebra: mixColor(WHITE, primary, 0.03),
  };
}

export const DERIVED_COLOR_KEYS = Object.keys(deriveBrandColors(BLACK, BLACK));
