/**
 * Zentrale Shortcut-Registry von hocX (design/KEYBOARD_ACCESSIBILITY.md, Abschnitt 3).
 *
 * Jede Produktivitäts-Tastenkombination steht hier genau einmal - mit Beschreibung
 * (Übersetzungsschlüssel unter `common.keyboard.shortcuts.<id>`), Scope und Regeln für
 * Eingabefelder und offene Overlays. Komponenten binden ihre Aktion mit `useShortcut(id, …)`
 * (lib/keyboard/use-shortcut.ts); die Shortcut-Hilfe («?») liest dieselbe Liste. Eine zweite,
 * manuell gepflegte Liste gibt es nicht.
 *
 * Standard-Interaktionen (Tab, Enter/Leertaste, Escape, Pfeile in Listen, Menüs, Tabs, Kalender)
 * sind keine Shortcuts: die liefern die Bausteine selbst. Damit sie in der Hilfe erscheinen,
 * stehen sie mit `kind: "standard"` hier, ohne Handler.
 *
 * Kombinationen (`keys`):
 *   "Mod"   = Strg (Windows/Linux) bzw. ⌘ (Apple); beide werden akzeptiert.
 *   "Alt"   = Alt bzw. ⌥ (Option). "Shift" = Umschalt bzw. ⇧.
 *   Taste   = Wert von `event.key` ("K", "Enter", "ArrowUp", "/", "?", "1" …).
 * event.key vs. event.code: Buchstaben ohne Alt werden über `event.key` erkannt, damit sie dem
 * aufgedruckten Zeichen folgen (Strg+Z bleibt auf QWERTZ und QWERTY «Z»). Mit Alt verändert macOS
 * (Option) und teils AltGr das Zeichen (⌥T = «†»), daher dort `event.code` (KeyT). Satzzeichen wie
 * «/» und «?» liegen je Layout auf anderen Tasten (CH/DE: Umschalt+7 bzw. Umschalt+') - sie
 * werden über `event.key` erkannt und Umschalt wird dabei ignoriert.
 */

export type ShortcutScope = "global" | "page" | "component";
export type ShortcutKind = "shortcut" | "standard";

export type ShortcutDefinition = {
  /** Stabile ID, zugleich Übersetzungsschlüssel `common.keyboard.shortcuts.<id mit _ statt .>` */
  id: string;
  /** Eine oder mehrere gleichwertige Kombinationen (siehe Kopfkommentar). */
  keys: readonly string[];
  /** Darstellung in der Hilfe, falls `keys` zu viele sind (z. B. «1–4»). */
  displayKeys?: readonly string[];
  scope: ShortcutScope;
  /** Gruppe in der Hilfe: «global», «lists», «dialogs», «protocol», «designer», «media» … */
  group: ShortcutGroup;
  /** Auch beim Tippen in einem Feld/Editor auslösen? Standard: nein. */
  inInputs?: boolean;
  /** Auch auslösen, wenn ein Dialog/Popover offen ist (und der Handler ausserhalb liegt)? Standard: nein. */
  whenOverlayOpen?: boolean;
  /** Bei «standard»: nur Dokumentation, kein Handler. */
  kind?: ShortcutKind;
  /** Bewusst übernommener Browser-Standard (siehe BROWSER_DEFAULT_COMBOS). */
  overridesBrowser?: boolean;
};

export const SHORTCUT_GROUPS = ["global", "lists", "dialogs", "reorder", "protocol", "designer", "media", "admin"] as const;
export type ShortcutGroup = (typeof SHORTCUT_GROUPS)[number];

/** Kombinationen, die Browser, Betriebssystem oder Screenreader brauchen - nie belegen. */
export const RESERVED_COMBOS = [
  "Mod+W", "Mod+T", "Mod+N", "Mod+Shift+N", "Mod+Shift+T", "Mod+Q", "Mod+L", "Mod+R", "Mod+P",
  "Mod+H", "Mod+J", "Mod+Tab", "Mod+Shift+Tab", "Alt+Tab", "Mod+C", "Mod+V", "Mod+X", "Mod+A",
  "Mod+Shift+Delete", "Mod+0", "Mod+Plus", "Mod+Minus", "Alt+ArrowLeft", "Alt+ArrowRight", "Alt+F4",
  "F1", "F5", "F6", "F7", "F11", "F12", "Mod+Alt+ArrowLeft", "Mod+Alt+ArrowRight", "Insert", "CapsLock",
] as const;

/**
 * Browser-Standards, die eine Seite nur bewusst übernehmen darf (`overridesBrowser: true`):
 * Suchen, Speichern, Lesezeichen. Das Feld zwingt zur Entscheidung im Review.
 */
export const BROWSER_DEFAULT_COMBOS = ["Mod+F", "Mod+S", "Mod+D", "Mod+K", "Mod+Z", "Mod+Y", "Mod+Shift+Z"] as const;

export const SHORTCUTS = [
  // ── Überall ──────────────────────────────────────────────────────────────
  { id: "global.search", keys: ["Mod+K"], overridesBrowser: true, scope: "global", group: "global", inInputs: true, whenOverlayOpen: true },
  { id: "global.listSearch", keys: ["Mod+F"], overridesBrowser: true, scope: "global", group: "global", inInputs: true, whenOverlayOpen: true },
  { id: "global.quickSearch", keys: ["/"], scope: "global", group: "global", whenOverlayOpen: true },
  { id: "global.help", keys: ["?"], scope: "global", group: "global" },
  // Im Suchfenster (global-search.tsx): Strg+F übernimmt den getippten Begriff in die Listensuche
  // der Seite. Das Suchfenster behandelt die Taste selbst, daher hier nur zur Anzeige.
  // Plattform-Admin (admin-shell.tsx): Sidebar kompakt/breit. «[» statt Mod+B (Browser: Lesezeichen)
  { id: "admin.toggleSidebar", keys: ["["], scope: "global", group: "admin" },
  // Audit-Log (admin-audit-log.tsx): nächster/vorheriger Eintrag in der Detail-Spalte
  { id: "admin.auditNext", keys: ["J"], scope: "page", group: "admin" },
  { id: "admin.auditPrevious", keys: ["K"], scope: "page", group: "admin" },
  { id: "search.toListSearch", keys: ["Mod+F"], overridesBrowser: true, scope: "component", group: "global", kind: "standard" },

  // ── Standard-Interaktionen (Bausteine, nur Hilfe) ────────────────────────
  { id: "standard.nextField", keys: ["Tab"], displayKeys: ["Tab", "Shift+Tab"], scope: "component", group: "dialogs", kind: "standard" },
  { id: "standard.activate", keys: ["Enter"], displayKeys: ["Enter", "Space"], scope: "component", group: "dialogs", kind: "standard" },
  { id: "standard.close", keys: ["Escape"], scope: "component", group: "dialogs", kind: "standard" },
  { id: "standard.listNavigate", keys: ["ArrowDown"], displayKeys: ["ArrowUp", "ArrowDown", "Home", "End"], scope: "component", group: "lists", kind: "standard" },
  { id: "standard.tabsNavigate", keys: ["ArrowRight"], displayKeys: ["ArrowLeft", "ArrowRight"], scope: "component", group: "lists", kind: "standard" },
  { id: "standard.reorder", keys: ["Alt+ArrowUp"], displayKeys: ["Alt+ArrowUp", "Alt+ArrowDown"], scope: "component", group: "reorder", kind: "standard" },

  // ── Protokoll-Editor ─────────────────────────────────────────────────────
  { id: "protocol.find", keys: ["Mod+F"], overridesBrowser: true, scope: "page", group: "protocol", inInputs: true },
  { id: "protocol.nextElement", keys: ["Mod+Enter"], scope: "page", group: "protocol", inInputs: true },
  { id: "protocol.previousElement", keys: ["Mod+Shift+Enter"], scope: "page", group: "protocol", inInputs: true },
  { id: "protocol.elementDown", keys: ["ArrowDown"], displayKeys: ["ArrowUp", "ArrowDown"], scope: "page", group: "protocol" },
  { id: "protocol.elementUp", keys: ["ArrowUp"], scope: "page", group: "protocol" },
  { id: "protocol.openTodo", keys: ["Mod+Alt+T"], scope: "page", group: "protocol", inInputs: true },
  { id: "protocol.openNotes", keys: ["Mod+Alt+N"], scope: "page", group: "protocol", inInputs: true },
  // Schnelle Pendenz (session-panel.tsx): Abgabe ein-/ausschalten, auch im Titelfeld
  { id: "protocol.quickTodoCollect", keys: ["Alt+A"], scope: "component", group: "protocol", inInputs: true },
  { id: "protocol.attendanceStatus", keys: ["1", "2", "3", "4"], displayKeys: ["1", "2", "3", "4"], scope: "component", group: "protocol" },

  // ── Document Studio (Designer) ───────────────────────────────────────────
  { id: "designer.save", keys: ["Mod+S"], overridesBrowser: true, scope: "page", group: "designer", inInputs: true },
  { id: "designer.undo", keys: ["Mod+Z"], overridesBrowser: true, scope: "page", group: "designer" },
  { id: "designer.redo", keys: ["Mod+Shift+Z", "Mod+Y"], overridesBrowser: true, scope: "page", group: "designer" },
  { id: "designer.duplicate", keys: ["Mod+D"], overridesBrowser: true, scope: "page", group: "designer" },
  { id: "designer.delete", keys: ["Delete", "Backspace"], scope: "page", group: "designer" },
  { id: "designer.move", keys: ["Alt+ArrowUp", "Alt+ArrowDown"], scope: "page", group: "designer" },
  { id: "designer.deselect", keys: ["Escape"], scope: "page", group: "designer" },

  // ── Fotos/Dateien ────────────────────────────────────────────────────────
  { id: "media.previous", keys: ["ArrowLeft", "J"], scope: "component", group: "media" },
  { id: "media.next", keys: ["ArrowRight", "L"], scope: "component", group: "media" },
] as const satisfies readonly ShortcutDefinition[];

export type ShortcutId = (typeof SHORTCUTS)[number]["id"];

const BY_ID = new Map<string, ShortcutDefinition>(SHORTCUTS.map((definition) => [definition.id, definition]));

export function getShortcut(id: ShortcutId): ShortcutDefinition {
  const definition = BY_ID.get(id);
  if (!definition) throw new Error(`Unbekannter Shortcut: ${id}`); // i18n-ok: Entwicklerfehler
  return definition;
}

/** Übersetzungsschlüssel relativ zu `common.keyboard.shortcuts` (Punkte → Unterstrich). */
export function shortcutMessageKey(id: string): string {
  return id.replace(/\./g, "_");
}

// ── Kombinationen parsen und vergleichen ──────────────────────────────────

export type ParsedCombo = { mod: boolean; alt: boolean; shift: boolean; key: string };

const MODIFIERS = new Set(["Mod", "Alt", "Shift"]);

export function parseCombo(combo: string): ParsedCombo {
  // «+» als Taste: «Mod+Plus»
  const parts = combo.split("+");
  const key = parts.pop() ?? "";
  for (const part of parts) {
    if (!MODIFIERS.has(part)) throw new Error(`Ungültiger Modifier «${part}» in «${combo}»`); // i18n-ok: Entwicklerfehler
  }
  if (!key) throw new Error(`Leere Taste in «${combo}»`); // i18n-ok: Entwicklerfehler
  return { mod: parts.includes("Mod"), alt: parts.includes("Alt"), shift: parts.includes("Shift"), key };
}

/** Normalform für Vergleiche/Konflikte: Reihenfolge Mod, Alt, Shift, Taste in Grossbuchstaben. */
export function normalizeCombo(combo: string): string {
  const parsed = parseCombo(combo);
  return [parsed.mod && "Mod", parsed.alt && "Alt", parsed.shift && "Shift", parsed.key.length === 1 ? parsed.key.toUpperCase() : parsed.key]
    .filter(Boolean)
    .join("+");
}

/** Zeichen, deren Lage vom Tastaturlayout abhängt (Umschalt wird ignoriert). */
const LAYOUT_SYMBOLS = new Set(["/", "?", "+", "-", "*", ".", ",", "#", "!"]);

type KeyLike = Pick<KeyboardEvent, "key" | "code" | "ctrlKey" | "metaKey" | "altKey" | "shiftKey"> & {
  getModifierState?: (key: string) => boolean;
};

export function matchesCombo(event: KeyLike, combo: string | ParsedCombo): boolean {
  const parsed = typeof combo === "string" ? parseCombo(combo) : combo;
  const mod = event.ctrlKey || event.metaKey;
  if (mod !== parsed.mod || event.altKey !== parsed.alt) return false;
  // AltGr (Windows meldet Strg+Alt) erzeugt Zeichen wie @ # | - nie als Shortcut deuten
  if (parsed.alt && event.getModifierState?.("AltGraph")) return false;
  const want = parsed.key;
  if (want.length === 1 && LAYOUT_SYMBOLS.has(want)) return event.key === want;
  if (event.shiftKey !== parsed.shift) return false;
  if (want.length === 1 && /[a-z0-9]/i.test(want)) {
    if (parsed.alt) return event.code === (/\d/.test(want) ? `Digit${want}` : `Key${want.toUpperCase()}`);
    return event.key.toLowerCase() === want.toLowerCase();
  }
  return event.key === want;
}

export function matchesShortcut(event: KeyLike, id: ShortcutId): boolean {
  return getShortcut(id).keys.some((combo) => matchesCombo(event, combo));
}

// ── Darstellung ───────────────────────────────────────────────────────────

/** Namen der Tasten; `t` kommt aus `useTranslations("common.keys")`. */
export type KeyNameTranslator = (key: "ctrl" | "alt" | "shift" | "enter" | "escape" | "space" | "tab" | "delete" | "backspace" | "home" | "end" | "pageUp" | "pageDown") => string;

const APPLE_SYMBOLS: Record<string, string> = { Mod: "⌘", Alt: "⌥", Shift: "⇧", Enter: "↩", Escape: "esc", Backspace: "⌫", Delete: "⌦", Tab: "⇥" };
const ARROWS: Record<string, string> = { ArrowUp: "↑", ArrowDown: "↓", ArrowLeft: "←", ArrowRight: "→" };
const NAMED: Record<string, Parameters<KeyNameTranslator>[0]> = {
  Enter: "enter", Escape: "escape", Space: "space", " ": "space", Tab: "tab", Delete: "delete", Backspace: "backspace",
  Home: "home", End: "end", PageUp: "pageUp", PageDown: "pageDown",
};

/**
 * Plattformgerechte Beschriftung als Liste einzelner Tasten (für <kbd>):
 * Apple: ["⌥", "⌘", "T"], sonst: ["Strg", "Alt", "T"].
 */
export function comboParts(combo: string, apple: boolean, t: KeyNameTranslator): string[] {
  const parsed = parseCombo(combo);
  const appleSymbol = apple ? APPLE_SYMBOLS[parsed.key] : undefined;
  const key = ARROWS[parsed.key] ?? appleSymbol ?? (NAMED[parsed.key] ? t(NAMED[parsed.key]) : parsed.key.length === 1 ? parsed.key.toUpperCase() : parsed.key);
  const parts: string[] = [];
  // Apple-Reihenfolge nach Human Interface Guidelines: ⌃ ⌥ ⇧ ⌘
  if (apple) {
    if (parsed.alt) parts.push(APPLE_SYMBOLS.Alt);
    if (parsed.shift) parts.push(APPLE_SYMBOLS.Shift);
    if (parsed.mod) parts.push(APPLE_SYMBOLS.Mod);
  } else {
    if (parsed.mod) parts.push(t("ctrl"));
    if (parsed.alt) parts.push(t("alt"));
    if (parsed.shift) parts.push(t("shift"));
  }
  parts.push(key);
  return parts;
}

/** Eine Kombination als Text: Apple «⌥⌘T», sonst «Strg+Alt+T». */
export function formatCombo(combo: string, apple: boolean, t: KeyNameTranslator): string {
  return comboParts(combo, apple, t).join(apple ? "" : "+");
}

/** Wert für `aria-keyshortcuts` (WAI-ARIA-Syntax, Strg und ⌘ als Alternativen). */
export function ariaKeyShortcuts(id: ShortcutId): string {
  return getShortcut(id)
    .keys.flatMap((combo) => {
      const parsed = parseCombo(combo);
      const key = parsed.key === " " ? "Space" : parsed.key;
      const rest = [parsed.alt && "Alt", parsed.shift && "Shift", key].filter(Boolean).join("+");
      return parsed.mod ? [`Control+${rest}`, `Meta+${rest}`] : [rest];
    })
    .join(" ");
}
