"use client";

import { useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";

import { ActionMenu } from "@/components/ui/action-menu";
import { Badge } from "@/components/ui/badge";
import { RichTextEditor } from "@/components/ui/rich-text-editor";
import { useConfirm } from "@/contexts/confirm-context";
import { useToast } from "@/contexts/toast-context";
import { browserApiFetch } from "@/lib/api/client";
import { ProtocolAgendaItem } from "@/types/api";

const SAVE_DELAY_MS = 800;

/** Anliegen eines Protokollabschnitts. Ohne Ersteller (der steht nur in der Liste unter
 *  «Anliegen»). Titel und Text speichern verzögert direkt am Anliegen. */
export function AgendaItemsSection({
  items,
  isReadOnly,
  heading,
  onChanged,
  onRemoved,
  onPostpone,
}: {
  items: ProtocolAgendaItem[];
  isReadOnly: boolean;
  /** Eigene Überschrift (Abschnitt «Weitere Anliegen»); sonst nur die Eyebrow. */
  heading?: string;
  onChanged: (item: ProtocolAgendaItem) => void;
  onRemoved: (itemId: string) => void;
  onPostpone: (item: ProtocolAgendaItem) => void;
}) {
  const t = useTranslations("agenda");
  if (items.length === 0) return null;
  return (
    <section className="card editor-block-card agenda-items-section">
      <div className="editor-panel-header">
        <div>
          <div className="eyebrow">{t("editor.eyebrow")}</div>
          {heading ? <h3>{heading}</h3> : null}
        </div>
      </div>
      <div className="agenda-items-list">
        {items.map((item) => (
          <AgendaItemCard
            key={item.id}
            item={item}
            readOnly={isReadOnly || !item.can_edit}
            onChanged={onChanged}
            onRemoved={onRemoved}
            onPostpone={onPostpone}
          />
        ))}
      </div>
    </section>
  );
}

function AgendaItemCard({
  item,
  readOnly,
  onChanged,
  onRemoved,
  onPostpone,
}: {
  item: ProtocolAgendaItem;
  readOnly: boolean;
  onChanged: (item: ProtocolAgendaItem) => void;
  onRemoved: (itemId: string) => void;
  onPostpone: (item: ProtocolAgendaItem) => void;
}) {
  const t = useTranslations("agenda");
  const showToast = useToast();
  const confirm = useConfirm();
  const [title, setTitle] = useState(item.title);
  const [body, setBody] = useState(item.body ?? "");
  const pending = useRef<{ title?: string; body?: string }>({});
  const timer = useRef<number | null>(null);

  // Änderungen anderer (Collab-Neuladen) übernehmen, solange hier nichts aussteht.
  useEffect(() => {
    if (Object.keys(pending.current).length === 0) {
      setTitle(item.title);
      setBody(item.body ?? "");
    }
  }, [item.title, item.body]);

  useEffect(() => () => {
    if (timer.current !== null) window.clearTimeout(timer.current);
  }, []);

  async function flush() {
    if (timer.current !== null) {
      window.clearTimeout(timer.current);
      timer.current = null;
    }
    const patch = pending.current;
    pending.current = {};
    if (Object.keys(patch).length === 0) return;
    if (patch.title !== undefined && !patch.title.trim()) {
      setTitle(item.title);
      delete patch.title;
      if (Object.keys(patch).length === 0) return;
    }
    try {
      const saved = await browserApiFetch<{ title: string; body?: string | null }>(`/api/agenda-items/${item.id}`, {
        method: "PATCH",
        body: JSON.stringify(patch),
      });
      onChanged({ ...item, title: saved.title, body: saved.body ?? null });
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("errorSave"), "error");
    }
  }

  function schedule(patch: { title?: string; body?: string }) {
    pending.current = { ...pending.current, ...patch };
    if (timer.current !== null) window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => void flush(), SAVE_DELAY_MS);
  }

  async function remove() {
    const ok = await confirm({ message: t("deleteConfirm", { title: item.title }), tone: "danger", confirmLabel: t("actionDelete") });
    if (!ok) return;
    try {
      await browserApiFetch(`/api/agenda-items/${item.id}`, { method: "DELETE" });
      onRemoved(item.id);
      showToast(t("deleted"), "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("errorDelete"), "error");
    }
  }

  return (
    <article className="agenda-item-card">
      <div className="agenda-item-card-header">
        <input
          className="agenda-item-card-title"
          aria-label={t("editor.titleLabel")}
          value={title}
          maxLength={500}
          readOnly={readOnly}
          onChange={(event) => {
            setTitle(event.target.value);
            schedule({ title: event.target.value });
          }}
          onBlur={() => void flush()}
        />
        {item.postponed_count > 0 && <Badge variant="warning">{t("postponedBadge", { count: item.postponed_count })}</Badge>}
        {!readOnly && (
          <ActionMenu
            ariaLabel={t("editor.actions")}
            items={[
              { label: t("actionPostpone"), onClick: () => void flush().then(() => onPostpone(item)) },
              { label: t("actionDelete"), onClick: () => void remove(), danger: true },
            ]}
          />
        )}
      </div>
      <div className="agenda-item-card-body" onBlur={() => void flush()}>
        <RichTextEditor
          value={body}
          readOnly={readOnly}
          placeholder={t("editor.bodyPlaceholder")}
          onChange={(markdown) => {
            setBody(markdown);
            schedule({ body: markdown });
          }}
        />
      </div>
    </article>
  );
}
