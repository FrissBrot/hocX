"use client";

import { FormEvent, useState } from "react";
import Link from "next/link";
import { useTranslations } from "next-intl";

import { CopyField } from "@/components/ui/copy-field";
import { SegmentedControl } from "@/components/ui/segmented-control";
import { useToast } from "@/contexts/toast-context";
import { browserApiFetch } from "@/lib/api/client";
import type { FileOverviewItem, ShareLink } from "@/types/api";
import { ShareExpiry, shareExpiryDate } from "./viewer-logic";

/** Inhalt des Teilen-Popovers: Freigabelink nur für dieses Foto. Nutzt den bestehenden Weg
 * POST /api/share-links mit genau einer Datei (Anbieter «share_link» der Zugangslinks, Rate-Limit
 * und Ablauf wie jeder Freigabelink). Foto-Metadaten mit der sicheren Vorgabe des Backends:
 * Aufnahmedatum ja, Standort und Kamera nein - wer mehr teilen will, nimmt die Mehrfachauswahl. */
export function PhotoViewerShare({ item, manageHref }: { item: FileOverviewItem; manageHref: "/tenant-settings/links" | "/shared-links" }) {
  const t = useTranslations("photos.viewer.share");
  const showToast = useToast();
  const [name, setName] = useState(item.original_name);
  const [expiry, setExpiry] = useState<ShareExpiry>("30");
  const [busy, setBusy] = useState(false);
  const [created, setCreated] = useState<ShareLink | null>(null);

  async function create(event: FormEvent) {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    try {
      const link = await browserApiFetch<ShareLink>("/api/share-links", {
        method: "POST",
        body: JSON.stringify({
          name: name.trim() || null,
          expires_at: shareExpiryDate(expiry),
          file_ids: [item.id],
          album_id: null,
          share_location: false,
          share_capture_date: true,
          share_camera: false,
        }),
      });
      if (link) setCreated(link);
    } catch (error) {
      showToast(error instanceof Error && error.message ? error.message : t("createFailed"), "error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="photo-viewer-pop">
      <div className="photo-viewer-pop-head">
        <strong>{t("title")}</strong>
        <span className="photo-viewer-pop-text">{t("intro")}</span>
      </div>
      {created ? (
        <div className="photo-viewer-pop-body">
          <CopyField label={t("linkLabel")} value={`${window.location.origin}${created.url}`} />
          <Link className="photo-viewer-pop-link" href={manageHref}>
            {manageHref === "/tenant-settings/links" ? t("manageSettings") : t("manageShared")}
          </Link>
        </div>
      ) : (
        <form className="photo-viewer-pop-body" onSubmit={create}>
          <label className="field-stack">
            <span className="field-label">{t("nameLabel")}</span>
            <input maxLength={120} value={name} onChange={(event) => setName(event.target.value)} />
          </label>
          <div className="field-stack">
            <span className="field-label" id={`pv-share-expiry-${item.id}`}>{t("expiryLabel")}</span>
            <SegmentedControl<ShareExpiry>
              aria-labelledby={`pv-share-expiry-${item.id}`}
              value={expiry}
              onChange={setExpiry}
              options={[
                { value: "7", label: t("expiry7") },
                { value: "30", label: t("expiry30") },
                { value: "never", label: t("expiryNever") },
              ]}
            />
          </div>
          <button type="submit" className="button-primary" disabled={busy}>
            {busy ? t("creating") : t("create")}
          </button>
        </form>
      )}
    </div>
  );
}
