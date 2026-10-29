"use client";

// Rückfrage zu «Termin entfernen» in einer Termin-Serie (EventSeriesGroup). Bietet optional an,
// die Tags vom Termin zu entfernen, wegen denen er im Punkt erscheint (Tag-Filter der
// Wiederholung, gleiche Teilstring-Logik wie eventMatchesFilter).

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";

import { Modal } from "@/components/ui/modal";
import { splitTags } from "@/lib/element-types/event-filter";

/** Tags des Termins, die auf einen der Filter-Tags passen (Gross/klein egal, Teilstring). */
export function matchingEventTags(eventTag: string | null | undefined, filterTags: string[]): string[] {
  const filters = filterTags.map((tag) => tag.toLowerCase());
  if (!filters.length) return [];
  return splitTags(eventTag).filter((tag) => filters.some((filter) => tag.toLowerCase().includes(filter)));
}

/** Tag-Text des Termins ohne die genannten Tags; leer = null. */
export function eventTagWithout(eventTag: string | null | undefined, remove: string[]): string | null {
  const rest = splitTags(eventTag).filter((tag) => !remove.includes(tag));
  return rest.length ? rest.join(",") : null;
}

type Props = {
  open: boolean;
  title: string;
  // Tags des Termins, die zum Filter passen (siehe matchingEventTags)
  tags: string[];
  busy: boolean;
  onClose: () => void;
  onConfirm: (removeTags: string[]) => void;
};

export function EventRemoveDialog({ open, title, tags, busy, onClose, onConfirm }: Props) {
  const t = useTranslations("protocols");
  const tc = useTranslations("common");
  const [selected, setSelected] = useState<string[]>([]);

  useEffect(() => {
    if (open) setSelected([]);
  }, [open]);

  function toggle(tag: string, checked: boolean) {
    setSelected((current) => (checked ? [...current, tag] : current.filter((item) => item !== tag)));
  }

  return (
    <Modal open={open} title={t("eventSeries.removeTitle")} onClose={onClose}>
      <div className="grid">
        <p>{t("eventSeries.removeDescription", { title })}</p>
        {tags.length ? (
          <div className="field-stack">
            <span className="field-help">{t("eventSeries.removeTagHint")}</span>
            {tags.map((tag) => (
              <label key={tag} className="checkbox-row">
                <input type="checkbox" checked={selected.includes(tag)} onChange={(event) => toggle(tag, event.target.checked)} disabled={busy} />
                <span>{t("eventSeries.removeTagLabel", { tag })}</span>
              </label>
            ))}
          </div>
        ) : null}
      </div>
      <div className="modal-actions">
        <button type="button" className="button-ghost" onClick={onClose} disabled={busy}>
          {tc("cancel")}
        </button>
        <button type="button" className="button-danger" onClick={() => onConfirm(selected)} disabled={busy}>
          {t("eventSeries.removeAction")}
        </button>
      </div>
    </Modal>
  );
}
