"use client";

import { useTranslations } from "next-intl";

import { Modal } from "@/components/ui/modal";
import { comboParts, KeyNameTranslator, SHORTCUT_GROUPS, SHORTCUTS, shortcutMessageKey, type ShortcutDefinition } from "@/lib/keyboard/registry";
import { useActiveShortcutIds } from "@/lib/keyboard/use-shortcut";
import { useIsApple, useModifierLabel } from "@/lib/search/shortcuts";

/**
 * Shortcut-Hilfe («?» oder Benutzermenü › Tastenkürzel). Erzeugt sich vollständig aus der
 * Registry (lib/keyboard/registry.ts): globale Kürzel und Standard-Tasten immer, Kürzel einer
 * Seite/Komponente nur, solange sie gerade gebunden sind - die Liste zeigt also, was hier und jetzt
 * gilt. Es gibt keine zweite, von Hand gepflegte Liste.
 */
export function ShortcutHelp({ open, onClose }: { open: boolean; onClose: () => void }) {
  const t = useTranslations("common.keyboard");
  const tKeys = useTranslations("common.keys");
  const apple = useIsApple();
  const modifier = useModifierLabel();
  const active = new Set<string>(useActiveShortcutIds());

  const visible = (SHORTCUTS as readonly ShortcutDefinition[]).filter(
    (definition) => definition.kind === "standard" || definition.scope === "global" || active.has(definition.id)
  );
  // Gleiche Beschreibung (z. B. Element hoch/runter) nur einmal zeigen
  const shown = visible.filter((definition) => !(definition.id === "protocol.elementUp" && visible.some((other) => other.id === "protocol.elementDown")));

  return (
    <Modal open={open} onClose={onClose} title={t("helpTitle")} description={t("helpDescription")} size="wide">
      <div className="shortcut-help">
        {SHORTCUT_GROUPS.map((group) => {
          const entries = shown.filter((definition) => definition.group === group);
          if (!entries.length) return null;
          return (
            <section key={group} className="shortcut-help-section" aria-labelledby={`shortcut-help-${group}`}>
              <h3 id={`shortcut-help-${group}`} className="shortcut-help-heading">
                {t(`groups.${group}`)}
              </h3>
              <ul className="shortcut-help-list">
                {entries.map((definition) => (
                  <li key={definition.id} className="shortcut-help-row">
                    <span className="shortcut-help-label">{t(`shortcuts.${shortcutMessageKey(definition.id)}`)}</span>
                    <span className="shortcut-help-keys">
                      {(definition.displayKeys ?? definition.keys).map((combo) => (
                        <span key={combo} className="shortcut-help-combo">
                          {comboParts(combo, apple, tKeys as unknown as KeyNameTranslator).map((part, index) => (
                            <kbd key={index} className="shortcut-help-kbd">
                              {part}
                            </kbd>
                          ))}
                        </span>
                      ))}
                    </span>
                  </li>
                ))}
              </ul>
            </section>
          );
        })}
        <p className="field-help shortcut-help-note">{t("inputsHint", { modifier })}</p>
      </div>
    </Modal>
  );
}
