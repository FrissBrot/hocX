"use client";

import type { useConfirm } from "@/contexts/confirm-context";
import { PhotoAlbum } from "@/types/api";

type ConfirmFn = ReturnType<typeof useConfirm>;
/** `t` aus useTranslations("photos.shareRelease"). */
type ShareReleaseT = (key: "title" | "ownerMessage" | "noOwnerMessage" | "confirmLabel", values?: Record<string, string | number>) => string;

/** Warnhinweis vor dem manuellen Hinzufügen zu einem geteilten Album: hinzugefügte Fotos sind
 * sofort für alle sichtbar, die Zugriff auf das Album haben. Bei ungeteilten Alben keine Rückfrage. */
export function confirmAddToSharedAlbum(confirm: ConfirmFn, t: ShareReleaseT, album: PhotoAlbum, count: number): Promise<boolean> {
  if (!album.is_shared) return Promise.resolve(true);
  return confirm({
    title: t("title"),
    message: album.owner_tenant_name
      ? t("ownerMessage", { count, albumName: album.name, owner: album.owner_tenant_name })
      : t("noOwnerMessage", { count, albumName: album.name }),
    confirmLabel: t("confirmLabel"),
  });
}

/** Schlanker Hinweis auf noch nicht freigegebene Fotos: sichtbar, aber ohne Alarmfarbe im Text. */
export function AlbumReleaseNotice({ message, children }: { message: React.ReactNode; children?: React.ReactNode }) {
  return (
    <div className="album-release-notice" role="status">
      <span className="album-release-notice-dot" aria-hidden="true" />
      <span className="album-release-notice-text">{message}</span>
      {children && <span className="album-release-notice-actions">{children}</span>}
    </div>
  );
}
