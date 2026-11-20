import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

import { locales } from "@/i18n/locale-config.generated";

import {
  ariaKeyShortcuts,
  BROWSER_DEFAULT_COMBOS,
  comboParts,
  formatCombo,
  matchesCombo,
  normalizeCombo,
  parseCombo,
  RESERVED_COMBOS,
  SHORTCUT_GROUPS,
  SHORTCUTS,
  shortcutMessageKey,
  type KeyNameTranslator,
  type ShortcutDefinition,
} from "./registry";

const definitions = SHORTCUTS as readonly ShortcutDefinition[];
const keyNames: KeyNameTranslator = (key) => ({ ctrl: "Strg", alt: "Alt", shift: "Umschalt", enter: "Enter", escape: "Esc", space: "Leertaste", tab: "Tab", delete: "Entf", backspace: "Rücktaste", home: "Pos1", end: "Ende", pageUp: "Bild auf", pageDown: "Bild ab" })[key];

function key(init: Partial<KeyboardEvent> & { key: string }) {
  return { code: "", ctrlKey: false, metaKey: false, altKey: false, shiftKey: false, ...init } as KeyboardEvent;
}

describe("Shortcut-Registry: Definitionen", () => {
  it("hat eindeutige IDs und nur gültige Kombinationen", () => {
    const ids = definitions.map((definition) => definition.id);
    expect(new Set(ids).size).toBe(ids.length);
    for (const definition of definitions) {
      expect(definition.keys.length, definition.id).toBeGreaterThan(0);
      for (const combo of [...definition.keys, ...(definition.displayKeys ?? [])]) expect(() => parseCombo(combo), `${definition.id}: ${combo}`).not.toThrow();
      expect(SHORTCUT_GROUPS).toContain(definition.group);
    }
  });

  it("belegt keine Kombination doppelt im selben Scope und Bereich", () => {
    const seen = new Map<string, string>();
    for (const definition of definitions.filter((entry) => entry.kind !== "standard")) {
      for (const combo of definition.keys) {
        const slot = `${definition.scope}|${definition.group}|${normalizeCombo(combo)}`;
        expect(seen.get(slot), `${definition.id} kollidiert mit ${seen.get(slot)} (${combo})`).toBeUndefined();
        seen.set(slot, definition.id);
      }
    }
  });

  it("nutzt keine reservierten Browser-/System-Kombinationen und übernimmt Browser-Standards nur bewusst", () => {
    const reserved = new Set(RESERVED_COMBOS.map(normalizeCombo));
    const browser = new Set(BROWSER_DEFAULT_COMBOS.map(normalizeCombo));
    for (const definition of definitions) {
      for (const combo of definition.keys) {
        expect(reserved.has(normalizeCombo(combo)), `${definition.id}: ${combo} ist reserviert`).toBe(false);
        if (browser.has(normalizeCombo(combo))) expect(definition.overridesBrowser, `${definition.id}: ${combo} braucht overridesBrowser`).toBe(true);
      }
    }
  });

  it("globale Einbuchstaben-Kürzel lösen nie beim Tippen aus", () => {
    for (const definition of definitions.filter((entry) => entry.kind !== "standard")) {
      const plain = definition.keys.some((combo) => {
        const parsed = parseCombo(combo);
        return !parsed.mod && !parsed.alt && parsed.key.length === 1;
      });
      if (plain) expect(definition.inInputs ?? false, definition.id).toBe(false);
    }
  });

  it("hat Beschreibung und Gruppentitel in allen Sprachen", () => {
    for (const locale of locales) {
      const common = JSON.parse(fs.readFileSync(path.join(__dirname, "..", "..", "messages", locale, "common.json"), "utf-8"));
      for (const definition of definitions) {
        const text = common.keyboard?.shortcuts?.[shortcutMessageKey(definition.id)];
        expect(typeof text === "string" && text.trim().length > 0, `${locale}: ${definition.id}`).toBe(true);
      }
      for (const group of SHORTCUT_GROUPS) expect(common.keyboard?.groups?.[group], `${locale}: Gruppe ${group}`).toBeTruthy();
      for (const name of ["ctrl", "alt", "shift", "enter", "escape", "space", "tab", "delete", "backspace", "home", "end", "pageUp", "pageDown"]) {
        expect(common.keys?.[name], `${locale}: Taste ${name}`).toBeTruthy();
      }
    }
  });
});

describe("Shortcut-Registry: Erkennen der Tasten", () => {
  it("Strg und ⌘ sind gleichwertig, Buchstaben folgen dem Layout (event.key)", () => {
    expect(matchesCombo(key({ key: "k", ctrlKey: true }), "Mod+K")).toBe(true);
    expect(matchesCombo(key({ key: "k", metaKey: true }), "Mod+K")).toBe(true);
    expect(matchesCombo(key({ key: "K", ctrlKey: true, shiftKey: true }), "Mod+K")).toBe(false);
    // QWERTZ: physische Y-Taste liefert «z» - Strg+Z ist das aufgedruckte Z
    expect(matchesCombo(key({ key: "z", code: "KeyY", ctrlKey: true }), "Mod+Z")).toBe(true);
    expect(matchesCombo(key({ key: "k" }), "Mod+K")).toBe(false);
  });

  it("mit Alt zählt die physische Taste (macOS-Option verändert das Zeichen)", () => {
    expect(matchesCombo(key({ key: "†", code: "KeyT", metaKey: true, altKey: true }), "Mod+Alt+T")).toBe(true);
    expect(matchesCombo(key({ key: "t", code: "KeyT", ctrlKey: true, altKey: true }), "Mod+Alt+T")).toBe(true);
  });

  it("AltGr (Windows: Strg+Alt) erzeugt Zeichen und ist nie ein Shortcut", () => {
    const altGr = { ...key({ key: "@", code: "Digit2", ctrlKey: true, altKey: true }), getModifierState: (name: string) => name === "AltGraph" };
    expect(matchesCombo(altGr, "Mod+Alt+2")).toBe(false);
  });

  it("Satzzeichen unabhängig von Umschalt und Layout (CH: / = Umschalt+7, ? = Umschalt+')", () => {
    expect(matchesCombo(key({ key: "/", code: "Digit7", shiftKey: true }), "/")).toBe(true);
    expect(matchesCombo(key({ key: "?", code: "Minus", shiftKey: true }), "?")).toBe(true);
    expect(matchesCombo(key({ key: "?", ctrlKey: true, shiftKey: true }), "?")).toBe(false);
  });
});

describe("Shortcut-Registry: Darstellung", () => {
  it("zeigt plattformgerecht ⌘/⌥/⇧ bzw. Strg/Alt/Umschalt", () => {
    expect(formatCombo("Mod+K", true, keyNames)).toBe("⌘K");
    expect(formatCombo("Mod+K", false, keyNames)).toBe("Strg+K");
    expect(formatCombo("Mod+Alt+T", true, keyNames)).toBe("⌥⌘T");
    expect(formatCombo("Mod+Alt+T", false, keyNames)).toBe("Strg+Alt+T");
    expect(formatCombo("Mod+Shift+Enter", true, keyNames)).toBe("⇧⌘↩");
    expect(comboParts("Alt+ArrowUp", false, keyNames)).toEqual(["Alt", "↑"]);
  });

  it("jede Kombination lässt sich auf beiden Plattformen darstellen, ohne fest eingebautes «Ctrl»", () => {
    for (const definition of definitions) {
      for (const combo of definition.displayKeys ?? definition.keys) {
        for (const apple of [true, false]) {
          const text = formatCombo(combo, apple, keyNames);
          expect(text.length, `${definition.id} ${combo}`).toBeGreaterThan(0);
          expect(text).not.toMatch(/Ctrl|Control|Meta/);
        }
      }
    }
  });

  it("liefert aria-keyshortcuts mit Strg- und ⌘-Variante", () => {
    expect(ariaKeyShortcuts("global.search")).toBe("Control+K Meta+K");
    expect(ariaKeyShortcuts("protocol.openTodo")).toBe("Control+Alt+T Meta+Alt+T");
  });
});
