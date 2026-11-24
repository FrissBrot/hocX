"use client";

import { useTranslations } from "next-intl";

import { CollaboratorAvatar } from "@/components/protocol/collaboration-presence";
import type { AttendanceTally } from "@/components/protocol/protocol-editor-shared";
import { useShortcutCombo } from "@/components/protocol/protocol-dock";
import { DocsLink } from "@/components/ui/help-popover";
import type { CollaboratorInfo } from "@/lib/hooks/use-protocol-collaboration";
import { comboParts, getShortcut, type KeyNameTranslator, type ShortcutId } from "@/lib/keyboard/registry";
import { useIsApple } from "@/lib/search/shortcuts";

/** Kürzel des Editors, die in der Schublade erklärt werden (Reihenfolge = Liste). */
const LISTED_SHORTCUTS: ShortcutId[] = [
  "protocol.find",
  "protocol.nextBlock",
  "protocol.previousBlock",
  "protocol.openNotes",
  "protocol.openTodo",
  "protocol.openAgenda",
  "protocol.openStatus",
  "protocol.attendanceStatus",
  "global.search",
];

export type PresenceEntry = CollaboratorInfo & { where?: string | null };

type Props = {
  /** Wer sonst gerade im Protokoll ist (mit «wo», sofern bekannt) */
  others: PresenceEntry[];
  /** Eigener Ort (aktiver Punkt) */
  selfWhere: string | null;
  connected: boolean;
  attendance: AttendanceTally | null;
  /** «Status zurücksetzen» (F22): Bezeichnung des vorherigen Status, null = nicht erlaubt */
  revertToLabel: string | null;
  reverting: boolean;
  onRevert: () => void;
};

/** Inhalt der Schublade «Status & Zusammenarbeit». */
export function ProtocolStatusDrawer({ others, selfWhere, connected, attendance, revertToLabel, reverting, onRevert }: Props) {
  const t = useTranslations("protocols.editor.drawer.status");
  const tShortcuts = useTranslations("common.keyboard.shortcuts");
  const tKeys = useTranslations("common.keys");
  const apple = useIsApple();
  const combo = useShortcutCombo();
  const presenceNote = !connected ? t("offline") : others.length === 0 ? t("alone") : null;

  return (
    <div className="protocol-status-drawer">
      <section className="protocol-drawer-section" aria-labelledby="protocol-status-active">
        <h3 className="protocol-drawer-section-title" id="protocol-status-active">{t("activeNow")}</h3>
        <ul className="protocol-presence-list">
          <li className="protocol-presence-row">
            <span className="protocol-presence-self" aria-hidden="true" />
            <span className="protocol-presence-name">{t("you")}</span>
            {selfWhere ? <span className="protocol-presence-where">{selfWhere}</span> : null}
          </li>
          {others.map((user) => (
            <li key={user.user_id} className="protocol-presence-row">
              <CollaboratorAvatar user={user} />
              <span className="protocol-presence-name">{user.display_name}</span>
              {user.where ? <span className="protocol-presence-where">{user.where}</span> : null}
            </li>
          ))}
        </ul>
        {presenceNote ? <p className="muted protocol-drawer-note">{presenceNote}</p> : null}
      </section>

      {attendance ? (
        <section className="protocol-drawer-section" aria-labelledby="protocol-status-attendance">
          <h3 className="protocol-drawer-section-title" id="protocol-status-attendance">{t("participants")}</h3>
          <dl className="protocol-status-tally">
            <div className="protocol-status-tally-row"><dt><span className="protocol-status-dot protocol-status-dot-present" aria-hidden="true" />{t("present")}</dt><dd>{attendance.present + attendance.late}</dd></div>
            <div className="protocol-status-tally-row"><dt><span className="protocol-status-dot protocol-status-dot-excused" aria-hidden="true" />{t("excused")}</dt><dd>{attendance.excused}</dd></div>
            <div className="protocol-status-tally-row"><dt><span className="protocol-status-dot protocol-status-dot-absent" aria-hidden="true" />{t("absent")}</dt><dd>{attendance.absent}</dd></div>
          </dl>
        </section>
      ) : null}

      {revertToLabel ? (
        <section className="protocol-drawer-section" aria-labelledby="protocol-status-revert">
          <h3 className="protocol-drawer-section-title" id="protocol-status-revert">{t("statusTitle")}</h3>
          <p className="muted protocol-drawer-note">{t("revertHint")}</p>
          <button type="button" className="button-secondary" disabled={reverting} onClick={onRevert}>
            {reverting ? "…" : t("revertTo", { status: revertToLabel })}
          </button>
        </section>
      ) : null}

      <section className="protocol-drawer-section" aria-labelledby="protocol-status-shortcuts">
        <h3 className="protocol-drawer-section-title" id="protocol-status-shortcuts">{t("shortcuts")}</h3>
        <ul className="protocol-shortcut-list">
          {LISTED_SHORTCUTS.map((id) => {
            const definition = getShortcut(id);
            // Mehrere gleichwertige Kombinationen (z. B. Pendenz: Strg+Alt+T oder Strg+Alt+P) alle zeigen
            const combos = definition.displayKeys ?? [definition.keys[0]];
            return (
              <li key={id} className="protocol-shortcut-row">
                <span>{tShortcuts(id.replace(/\./g, "_"))}</span>
                <span className="protocol-shortcut-keys">
                  {combos.map((combo, comboIndex) => (
                    <span key={combo} className="protocol-shortcut-combo">
                      {comboIndex > 0 ? <span className="protocol-shortcut-or" aria-hidden="true">/</span> : null}
                      {comboParts(combo, apple, tKeys as unknown as KeyNameTranslator).map((part, index) => (
                        <kbd key={index} className="protocol-header-kbd">{part}</kbd>
                      ))}
                    </span>
                  ))}
                </span>
              </li>
            );
          })}
          <li className="protocol-shortcut-row">
            <span>{t("escape")}</span>
            <span className="protocol-shortcut-keys"><kbd className="protocol-header-kbd">{tKeys("escape")}</kbd></span>
          </li>
        </ul>
        <p className="field-help">{t("secondFind", { shortcut: combo("protocol.find") })}</p>
      </section>

      <DocsLink page="protokolle" anchor="mehrbenutzer">{t("docsLink")}</DocsLink>
    </div>
  );
}
