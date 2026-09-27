"use client";

import type { useConfirm } from "@/contexts/confirm-context";
import { PhotoAlbum } from "@/types/api";

type ConfirmFn = ReturnType<typeof useConfirm>;

function photoCount(count: number) {
  return count === 1 ? "1 Foto" : `${count} Fotos`;
}

/** Warnhinweis vor dem manuellen Hinzufügen zu einem geteilten Album: hinzugefügte Fotos sind
 * sofort für alle sichtbar, die Zugriff auf das Album haben. Bei ungeteilten Alben keine Rückfrage. */
export function confirmAddToSharedAlbum(confirm: ConfirmFn, album: PhotoAlbum, count: number): Promise<boolean> {
  if (!album.is_shared) return Promise.resolve(true);
  return confirm({
    title: "Fotos werden geteilt",
    message: album.owner_tenant_name
      ? `„${album.name}“ wird von ${album.owner_tenant_name} geteilt. ${photoCount(count)} ${count === 1 ? "ist" : "sind"} danach für alle Beteiligten sichtbar.`
      : `„${album.name}“ ist geteilt. ${photoCount(count)} ${count === 1 ? "wird" : "werden"} damit sofort für alle Mandanten und Links freigegeben, die Zugriff auf das Album haben.`,
    confirmLabel: "Hinzufügen und teilen",
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
