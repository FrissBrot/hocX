"use client";

import Link from "next/link";
import type { Route } from "next";
import { useTranslations } from "next-intl";

import type { FileOverviewItem } from "@/types/api";
import { isDeletable } from "./viewer-logic";

/** Inhalt des Löschen-Popovers. Direkt-Uploads: Rückfrage «In den Papierkorb» mit Hinweis aufs
 * Wiederherstellen. Fotos aus Protokoll, Abgabe & Co.: «Hier nicht löschbar», mit Link zur
 * Herkunft - dort entfernt, verschwinden sie auch aus der Galerie. */
export function PhotoViewerDelete({
  item,
  busy,
  onCancel,
  onConfirm,
}: {
  item: FileOverviewItem;
  busy: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  const t = useTranslations("photos.viewer.delete");
  if (!isDeletable(item)) {
    const origin = item.context_label || item.ref_label || item.origin_tag;
    return (
      <div className="photo-viewer-pop">
        <div className="photo-viewer-pop-head">
          <strong>{t("lockedTitle")}</strong>
          <span className="photo-viewer-pop-text">{t("lockedText", { origin })}</span>
        </div>
        {item.ref_href ? (
          <Link className="photo-viewer-pop-link" href={item.ref_href as Route}>
            {t("lockedLink", { origin: item.origin_tag })}
          </Link>
        ) : null}
      </div>
    );
  }
  return (
    <div className="photo-viewer-pop">
      <div className="photo-viewer-pop-head">
        <strong>{t("title")}</strong>
        <span className="photo-viewer-pop-text">{t("text", { name: item.original_name })}</span>
      </div>
      <div className="photo-viewer-pop-actions">
        <button type="button" className="button-ghost" onClick={onCancel} disabled={busy}>{t("cancel")}</button>
        <button type="button" className="button-danger" onClick={onConfirm} disabled={busy}>{t("confirm")}</button>
      </div>
    </div>
  );
}
