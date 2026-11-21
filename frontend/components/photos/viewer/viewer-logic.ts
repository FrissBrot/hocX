// Reine Logik der Foto-Ansicht (Design «hocX Foto-Ansicht»): Löschbarkeit, Vergleichsentscheid,
// Vorschau beim Verschieben des Aufnahmedatums, Analyse-Stufen. Ohne React, damit Vitest das
// Verhalten direkt prüft; die Komponenten in diesem Ordner rufen nur diese Funktionen auf.
import type { FileOverviewItem, SimilarityGroup, StoredFileMetadata } from "@/types/api";

type TFunc = (key: string, values?: Record<string, string | number | Date>) => string;

// ── Löschen ──────────────────────────────────────────────────────────────────────────────────

/** In den Papierkorb darf nur ein Direkt-Upload der Galerie (Backend: file_trash_service,
 * `_is_gallery_main`). Fotos aus Protokollen, Abgaben, Word-Importen und Exporten gehören zu
 * ihrer Herkunft und werden dort entfernt - das Backend lehnt sie ohnehin ab. */
export function isDeletable(item: Pick<FileOverviewItem, "source">): boolean {
  return item.source === "gallery_upload";
}

// ── Vergleich (Duplikate / ähnliche Aufnahmen) ───────────────────────────────────────────────

export type CompareDecision = "keep" | "trash";
export type CompareDecisions = Record<string, CompareDecision>;

/** Vorschlag beim Öffnen des Vergleichs: das beste Bild und alles Nicht-Löschbare bleibt, der Rest
 * geht in den Papierkorb. Ohne Vorschlag (`prefill = false`) bleibt alles. */
export function compareSuggestion(group: SimilarityGroup, prefill = true): CompareDecisions {
  return Object.fromEntries(
    group.images.map((image) => [image.id, !prefill || image.id === group.best_id || !isDeletable(image) ? "keep" : "trash"])
  );
}

/** «Alle behalten». */
export function keepAllDecisions(group: SimilarityGroup): CompareDecisions {
  return Object.fromEntries(group.images.map((image) => [image.id, "keep" as const]));
}

/** Entscheid für ein Bild umschalten - nicht löschbare Bilder bleiben immer. */
export function setDecision(decisions: CompareDecisions, image: FileOverviewItem, decision: CompareDecision): CompareDecisions {
  if (decision === "trash" && !isDeletable(image)) return decisions;
  return { ...decisions, [image.id]: decision };
}

export function toggleDecision(decisions: CompareDecisions, image: FileOverviewItem): CompareDecisions {
  return setDecision(decisions, image, decisions[image.id] === "trash" ? "keep" : "trash");
}

/** Zusammenfassung «N behalten · M in den Papierkorb» und die IDs, die «Anwenden» löscht. Ein
 * nicht löschbares Bild zählt immer als behalten, auch wenn ein alter Entscheid etwas anderes sagt. */
export function compareSummary(group: SimilarityGroup, decisions: CompareDecisions): { keep: number; trash: number; trashIds: string[] } {
  const trashIds = group.images.filter((image) => decisions[image.id] === "trash" && isDeletable(image)).map((image) => image.id);
  return { keep: group.images.length - trashIds.length, trash: trashIds.length, trashIds };
}

/** Schlüssel einer Gruppe für «geprüft»: Art + bestes Bild (wie die Tabs Duplikate/Ähnliche). */
export function groupKey(kind: SimilarityKind, group: Pick<SimilarityGroup, "best_id">): string {
  return `${kind}:${group.best_id}`;
}

export type SimilarityKind = "duplicate" | "series";
export type ViewerGroup = { kind: SimilarityKind; key: string; group: SimilarityGroup };

/** Gruppen, in denen das Foto steckt und die noch zu prüfen sind (mindestens zwei Bilder übrig,
 * nicht als geprüft markiert). Duplikate zuerst. */
export function groupsForItem(
  itemId: string,
  duplicates: SimilarityGroup[] | null,
  series: SimilarityGroup[] | null,
  reviewed: ReadonlySet<string>
): ViewerGroup[] {
  const result: ViewerGroup[] = [];
  for (const [kind, groups] of [["duplicate", duplicates], ["series", series]] as const) {
    for (const group of groups ?? []) {
      const key = groupKey(kind, group);
      if (group.images.length < 2 || reviewed.has(key)) continue;
      if (group.images.some((image) => image.id === itemId)) result.push({ kind, key, group });
    }
  }
  return result;
}

/** Wohin die Ansicht nach dem Löschen springt: das aktuelle Foto, sonst das beste übrige Bild der
 * Gruppe, sonst das nächste übrige. */
export function nextAfterRemoval(currentId: string, removed: string[], group: SimilarityGroup | null): string | null {
  const gone = new Set(removed);
  if (!gone.has(currentId)) return currentId;
  if (group) {
    if (!gone.has(group.best_id)) return group.best_id;
    const rest = group.images.find((image) => !gone.has(image.id));
    if (rest) return rest.id;
  }
  return null;
}

// ── Filmstreifen ─────────────────────────────────────────────────────────────────────────────

/** Ausschnitt rund um das aktuelle Foto - die Galerie kann tausende Fotos geladen haben. */
export function filmstripRange(index: number, length: number, radius = 30): [number, number] {
  const start = Math.max(0, Math.min(index - radius, length - 2 * radius - 1));
  return [start, Math.min(length, start + 2 * radius + 1)];
}

// ── Aufnahmedatum ────────────────────────────────────────────────────────────────────────────

export type CaptureDateKind = "corrected" | "exif" | "estimated" | "unknown";

/** Welche Art Datum gerade gilt - dieselbe Reihenfolge wie im Backend (capture_date.py). */
export function captureDateKind(metadata: Pick<StoredFileMetadata, "capture_corrected_at" | "exif_taken_at" | "estimated_taken_on">): CaptureDateKind {
  if (metadata.capture_corrected_at) return "corrected";
  if (metadata.exif_taken_at) return "exif";
  if (metadata.estimated_taken_on) return "estimated";
  return "unknown";
}

export type CaptureMoment = { date: string; time: string | null };

const WALL_CLOCK = /^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2}))?/;

function wallClock(value: string): { y: number; m: number; d: number; hh: number; mm: number } | null {
  const match = WALL_CLOCK.exec(value);
  if (!match) return null;
  return { y: Number(match[1]), m: Number(match[2]), d: Number(match[3]), hh: Number(match[4] ?? 12), mm: Number(match[5] ?? 0) };
}

const pad = (value: number) => String(value).padStart(2, "0");

/** Ausgangspunkt fürs Verschieben wie `image_metadata_service.shift_base`: Korrektur, sonst EXIF,
 * sonst Schätzung (ohne Uhrzeit, technisch 12:00). Die Zeiten sind Kamerazeit ohne Zeitzone - die
 * Ziffern im ISO-String gelten, nie die Zeitzone des Browsers. */
export function shiftBase(
  metadata: Pick<StoredFileMetadata, "capture_corrected_at" | "capture_corrected_has_time" | "exif_taken_at" | "estimated_taken_on">
): { value: string; hasTime: boolean } | null {
  if (metadata.capture_corrected_at) return { value: metadata.capture_corrected_at, hasTime: Boolean(metadata.capture_corrected_has_time) };
  if (metadata.exif_taken_at) return { value: metadata.exif_taken_at, hasTime: true };
  if (metadata.estimated_taken_on) return { value: `${metadata.estimated_taken_on}T12:00`, hasTime: false };
  return null;
}

/** Vorschau «Neu: …» beim Verschieben um Tage/Stunden - rechnet wie das Backend
 * (`shifted_correction`): Ausgangszeit + Versatz; ohne Uhrzeit zählt nur der neue Kalendertag.
 * Null, wenn das Foto kein Aufnahmedatum hat (Uploaddatum wird nie verschoben). */
export function shiftPreview(
  metadata: Pick<StoredFileMetadata, "capture_corrected_at" | "capture_corrected_has_time" | "exif_taken_at" | "estimated_taken_on">,
  days: number,
  hours: number
): CaptureMoment | null {
  const base = shiftBase(metadata);
  const parts = base ? wallClock(base.value) : null;
  if (!base || !parts) return null;
  // UTC-Arithmetik: keine Sommerzeit-Sprünge, die Ziffern bleiben Kamerazeit.
  const moment = new Date(Date.UTC(parts.y, parts.m - 1, parts.d, parts.hh, parts.mm) + (days * 24 + hours) * 3_600_000);
  const date = `${moment.getUTCFullYear()}-${pad(moment.getUTCMonth() + 1)}-${pad(moment.getUTCDate())}`;
  return { date, time: base.hasTime ? `${pad(moment.getUTCHours())}:${pad(moment.getUTCMinutes())}` : null };
}

/** Ganzzahl aus einem Feld («», «-» = 0), sonst null (ungültig). */
export function parseWholeNumber(value: string): number | null {
  const trimmed = value.trim();
  if (trimmed === "" || trimmed === "-") return 0;
  const parsed = Number(trimmed);
  return Number.isInteger(parsed) ? parsed : null;
}

// ── Freigabelink ─────────────────────────────────────────────────────────────────────────────

export type ShareExpiry = "7" | "30" | "never";

/** Ablaufdatum (ISO-Tag, Ende des Tages setzt das Backend) für «7 Tage»/«30 Tage», null = unbegrenzt. */
export function shareExpiryDate(expiry: ShareExpiry, today: Date = new Date()): string | null {
  if (expiry === "never") return null;
  const target = new Date(today.getFullYear(), today.getMonth(), today.getDate() + Number(expiry));
  return `${target.getFullYear()}-${pad(target.getMonth() + 1)}-${pad(target.getDate())}`;
}

// ── Analyse ──────────────────────────────────────────────────────────────────────────────────

// Schärfe und Gesichtsqualität sind rohe Laplace-Varianzen ohne Obergrenze (typisch ~10 bis
// mehrere Tausend, stark motiv- und rauschabhängig). Für die Anzeige werden sie logarithmisch
// auf 0-100 abgebildet und in Stufen beschriftet; der Rohwert steht im Tooltip.
const SHARPNESS_LOG_CEILING = Math.log10(1 + 10000);

export function sharpnessFraction(score: number): number {
  return Math.min(1, Math.max(0, Math.log10(1 + Math.max(0, score)) / SHARPNESS_LOG_CEILING));
}

export type SharpnessLevel = "blurry" | "medium" | "sharp" | "verySharp";
export type ExposureLevel = "good" | "slight" | "strong";

export function sharpnessLevel(score: number): SharpnessLevel {
  return score < 50 ? "blurry" : score < 300 ? "medium" : score < 1500 ? "sharp" : "verySharp";
}

export function exposureLevel(score: number): ExposureLevel {
  return score >= 0.95 ? "good" : score >= 0.85 ? "slight" : "strong";
}

/** `t` aus useTranslations("photos.viewer"). */
export function describeSharpness(score: number, t: TFunc): string {
  return t("sharpnessFormat", { label: t(`sharpnessLevels.${sharpnessLevel(score)}`), percent: Math.round(sharpnessFraction(score) * 100) });
}

export function describeExposure(score: number, t: TFunc): string {
  return t("exposureFormat", { label: t(`exposureLevels.${exposureLevel(score)}`), percent: Math.round(score * 100) });
}
