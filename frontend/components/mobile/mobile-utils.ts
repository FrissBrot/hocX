import { TAG_COLORS } from "@/components/ui/tag-input";
import { fallbackTagColor } from "@/components/events/event-utils";
import type { TagConfig } from "@/lib/hooks/use-tag-config";
import { toIntlLocale } from "@/lib/utils/format";
import type { TodoListItem } from "@/types/api";

// Reine Hilfsfunktionen der Mobile-Oberflaeche - ohne Hooks, uebersetzte Texte kommen als `t`
// herein (Muster wie app-shell-nav.ts::formatRoleLabel).

export type TFunc = (key: string, values?: Record<string, string | number | Date>) => string;

/** Heutiges Datum als ISO-String (JJJJ-MM-TT) in der Zeitzone des Geraets. */
export function todayIso(): string {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
}

function isoToUtc(iso: string): Date {
  const [year, month, day] = iso.slice(0, 10).split("-").map(Number);
  return new Date(Date.UTC(year, (month || 1) - 1, day || 1));
}

/** Tage von `from` bis `to` (positiv = `to` liegt in der Zukunft). */
export function daysBetween(from: string, to: string): number {
  return Math.round((isoToUtc(to).getTime() - isoToUtc(from).getTime()) / 86_400_000);
}

function formatParts(iso: string, locale: string, options: Intl.DateTimeFormatOptions): string {
  return new Intl.DateTimeFormat(toIntlLocale(locale), { ...options, timeZone: "UTC" }).format(isoToUtc(iso));
}

export const dateParts = {
  day: (iso: string) => String(isoToUtc(iso).getUTCDate()),
  weekdayShort: (iso: string, locale: string) => formatParts(iso, locale, { weekday: "short" }).replace(".", ""),
  monthShort: (iso: string, locale: string) => formatParts(iso, locale, { month: "short" }).replace(".", ""),
  monthYear: (iso: string, locale: string) => formatParts(iso, locale, { month: "long", year: "numeric" }),
  dayMonth: (iso: string, locale: string) => formatParts(iso, locale, { day: "numeric", month: "short" }),
  weekdayDayMonth: (iso: string, locale: string) => formatParts(iso, locale, { weekday: "short", day: "numeric", month: "short" }),
  long: (iso: string, locale: string) => formatParts(iso, locale, { weekday: "long", day: "numeric", month: "long", year: "numeric" }),
  weekdayLongDayMonth: (iso: string, locale: string) => formatParts(iso, locale, { weekday: "long", day: "numeric", month: "long" }),
};

/** "Heute", "Morgen", "In 5 Tagen", "Vor 3 Tagen" - Texte aus mobile.relative.*. */
export function relativeDay(iso: string, t: TFunc): string {
  const diff = daysBetween(todayIso(), iso);
  if (diff === 0) return t("relative.today");
  if (diff === 1) return t("relative.tomorrow");
  if (diff === -1) return t("relative.yesterday");
  return diff > 0 ? t("relative.inDays", { count: diff }) : t("relative.daysAgo", { count: -diff });
}

export function isTodoDone(todo: Pick<TodoListItem, "todo_status_code">): boolean {
  return todo.todo_status_code === "done" || todo.todo_status_code === "cancelled";
}

export function isTodoOverdue(todo: Pick<TodoListItem, "todo_status_code" | "resolved_due_date">): boolean {
  return !isTodoDone(todo) && !!todo.resolved_due_date && todo.resolved_due_date.slice(0, 10) < todayIso();
}

/** Stabile Farbe pro Tag: konfigurierte Tag-Farbe, sonst dieselbe Fallback-Palette wie Desktop. */
export function tagColor(tag: string, tagConfig: TagConfig): string {
  return tagConfig[tag]?.color ?? fallbackTagColor(tag);
}

/** Avatar-Farbe pro Name aus der Tag-Palette (bewusste Ausnahme "Avatar-Farben", DESIGN.md). */
export function avatarColor(name: string): string {
  let hash = 0;
  for (let index = 0; index < name.length; index += 1) {
    hash = (hash * 31 + name.charCodeAt(index)) | 0;
  }
  return TAG_COLORS[Math.abs(hash) % (TAG_COLORS.length - 1)];
}

export function initials(name: string | null | undefined): string {
  return (name ?? "")
    .split(/\s+/)
    .filter(Boolean)
    .map((part) => part[0])
    .join("")
    .slice(0, 2)
    .toUpperCase();
}
