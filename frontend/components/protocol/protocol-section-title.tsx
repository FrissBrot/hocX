"use client";

import { useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";

import { ActionMenu, type ActionMenuItem } from "@/components/ui/action-menu";
import { Badge } from "@/components/ui/badge";

type Props = {
  elementId: string;
  number: number;
  title: string;
  /** Titel laut Vorlage, wenn im Protokoll umbenannt (API template_title) */
  templateTitle?: string | null;
  hidden: boolean;
  /** Umbenennen/Ausblenden erlaubt (bearbeitbar, nicht «Sitzungsnotizen») */
  canRename: boolean;
  canToggleHidden: boolean;
  onRename: (elementId: string, title: string) => Promise<boolean>;
  onToggleHidden: (elementId: string, visible: boolean) => void;
  children?: React.ReactNode;
};

/**
 * Kopf eines Punkts im Dokument: Nummer, Titel (Serif) und Hinweise; mit Recht ein Menü zum
 * Umbenennen (Titel wird zum Eingabefeld, Enter speichert, Escape bricht ab) und Aus-/Einblenden.
 * Änderungen gelten nur in diesem Protokoll - in die Vorlage kommen sie erst über den Dialog beim
 * Abschliessen.
 */
export function ProtocolSectionTitle({ elementId, number, title, templateTitle, hidden, canRename, canToggleHidden, onRename, onToggleHidden, children }: Props) {
  const t = useTranslations("protocols.editor.section");
  const tPoint = useTranslations("protocols");
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(title);
  const [saving, setSaving] = useState(false);
  const inputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    if (editing) inputRef.current?.select();
  }, [editing]);

  async function save() {
    const next = draft.trim();
    if (!next || next === title) {
      setEditing(false);
      return;
    }
    setSaving(true);
    const ok = await onRename(elementId, next);
    setSaving(false);
    if (ok) setEditing(false);
  }

  const items: ActionMenuItem[] = [
    ...(canRename ? [{ label: t("rename"), onClick: () => { setDraft(title); setEditing(true); } }] : []),
    ...(canToggleHidden ? [{ label: hidden ? t("show") : t("hide"), onClick: () => onToggleHidden(elementId, hidden) }] : []),
  ];

  return (
    <header className="protocol-doc-section-head">
      <span className="protocol-doc-section-number" aria-hidden="true">{String(number).padStart(2, "0")}</span>
      {editing ? (
        <input
          ref={inputRef}
          className="protocol-doc-section-title-input"
          value={draft}
          maxLength={200}
          aria-label={t("renameLabel")}
          disabled={saving}
          onChange={(event) => setDraft(event.target.value)}
          onBlur={() => void save()}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              event.preventDefault();
              void save();
            } else if (event.key === "Escape") {
              event.preventDefault();
              setDraft(title);
              setEditing(false);
            }
          }}
        />
      ) : (
        <h2 className="protocol-doc-section-title" id={`protocol-element-title-${elementId}`}>
          <span className="visually-hidden">{tPoint("elementPointNumber", { number })} </span>
          {title}
        </h2>
      )}
      {templateTitle ? <span title={t("renamedTitle", { title: templateTitle })}><Badge variant="neutral">{t("renamed")}</Badge></span> : null}
      {hidden ? <Badge variant="warning">{t("hiddenBadge")}</Badge> : null}
      {children}
      {items.length && !editing ? (
        <span className="protocol-doc-section-menu">
          <ActionMenu ariaLabel={t("menu", { title })} items={items} triggerClassName="button-ghost button-icon protocol-doc-section-menu-trigger" />
        </span>
      ) : null}
    </header>
  );
}
