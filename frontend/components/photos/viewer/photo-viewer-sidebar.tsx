"use client";

import { useEffect, useState } from "react";
import { useLocale, useTranslations } from "next-intl";

import { SearchableMultiSelect } from "@/components/ui/searchable-select";
import { TagInput } from "@/components/ui/tag-input";
import { useConfirm } from "@/contexts/confirm-context";
import { useToast } from "@/contexts/toast-context";
import { browserApiBaseUrl, browserApiFetch } from "@/lib/api/client";
import { formatDateTime, formatFileSize } from "@/lib/utils/format";
import type { FileAlbumRef, FileOverviewItem, PhotoAlbum, StoredFileMetadata } from "@/types/api";
import { confirmAddToSharedAlbum } from "../album-share-release";
import { CaptureDateBox } from "./capture-date-box";
import { describeExposure, describeSharpness, sharpnessFraction, ViewerGroup } from "./viewer-logic";

type Props = {
  item: FileOverviewItem;
  metadata: StoredFileMetadata | null;
  /** Null: Abschnitt ausgeblendet (ohne photos.manage lässt sich nichts aufräumen). */
  groups: ViewerGroup[] | null;
  canManage: boolean;
  albums: FileAlbumRef[];
  tagsValue: string;
  saving: boolean;
  onOpenGroup: (key: string) => void;
  onCaptureDateSaved: (metadata: StoredFileMetadata) => void;
  onAlbumsChange: (albums: FileAlbumRef[]) => void;
  onTagsChange: (value: string) => void;
};

/** Rechte Seitenleiste der Foto-Ansicht (Design: 368 px, unter 900 px unter dem Bild). Folgt dem
 * App-Theme (Tokens --panel/--text …), damit Felder und Auswahllisten wie überall aussehen. */
export function PhotoViewerSidebar(props: Props) {
  const t = useTranslations("photos.viewer");
  const { item, metadata } = props;
  return (
    <aside className="photo-viewer-sidebar" aria-label={t("sidebarLabel")}>
      {props.groups ? (
        <section className="photo-viewer-section" aria-labelledby="pv-groups-title">
          <h2 className="photo-viewer-section-title" id="pv-groups-title">{t("groups.title")}</h2>
          {props.groups.length === 0 ? (
            <p className="photo-viewer-empty">{t("groups.empty")}</p>
          ) : (
            props.groups.map((entry) => <GroupCard key={entry.key} entry={entry} currentId={item.id} onOpen={() => props.onOpenGroup(entry.key)} />)
          )}
        </section>
      ) : null}

      <section className="photo-viewer-section" aria-labelledby="pv-date-title">
        <h2 className="photo-viewer-section-title" id="pv-date-title">{t("dateBox.title")}</h2>
        <CaptureDateBox key={item.id} fileId={item.id} metadataUrl={item.metadata_url} metadata={metadata} onSaved={props.onCaptureDateSaved} />
      </section>

      <AlbumSection item={item} albums={props.albums} canManage={props.canManage} onChange={props.onAlbumsChange} />

      <section className="photo-viewer-section" aria-labelledby="pv-tags-title">
        <h2 className="photo-viewer-section-title" id="pv-tags-title">
          {t("tagsSection")} {props.saving ? <span className="photo-viewer-saving">{t("savingSuffix")}</span> : null}
        </h2>
        <TagInput value={props.tagsValue} onChange={props.onTagsChange} placeholder={t("tagPlaceholder")} alwaysShowPlaceholder readOnly={!props.canManage} />
      </section>

      <AnalysisSection item={item} />
      <DetailsSection item={item} metadata={metadata} albums={props.albums} />
    </aside>
  );
}

function GroupCard({ entry, currentId, onOpen }: { entry: ViewerGroup; currentId: string; onOpen: () => void }) {
  const t = useTranslations("photos.viewer.groups");
  const others = entry.group.images.length - 1;
  const best = entry.group.images.find((image) => image.id === entry.group.best_id);
  return (
    <button type="button" className={`photo-viewer-group-card photo-viewer-group-card-${entry.kind}`} onClick={onOpen}>
      <span className="photo-viewer-group-thumbs" aria-hidden="true">
        {entry.group.images.slice(0, 4).map((image) => (
          <img key={image.id} src={`${browserApiBaseUrl}${image.thumbnail_url ?? image.content_url}`} alt="" loading="lazy" decoding="async" />
        ))}
      </span>
      <span className="photo-viewer-group-text">
        <strong>{entry.kind === "duplicate" ? t("duplicates", { count: others }) : t("similar", { count: others })}</strong>
        <span>{entry.group.best_id === currentId ? t("thisIsBest") : t("bestIs", { name: best?.original_name ?? "" })}</span>
      </span>
      <span className="photo-viewer-group-cta">{t("compare")}</span>
    </button>
  );
}

function AlbumSection({ item, albums, canManage, onChange }: { item: FileOverviewItem; albums: FileAlbumRef[]; canManage: boolean; onChange: (albums: FileAlbumRef[]) => void }) {
  const t = useTranslations("photos.viewer.albums");
  const tShareRelease = useTranslations("photos.shareRelease");
  const confirm = useConfirm();
  const showToast = useToast();
  const [options, setOptions] = useState<PhotoAlbum[] | null>(null);
  const [busy, setBusy] = useState(false);

  // Einmal je geöffneter Ansicht (die Sektion bleibt beim Blättern bestehen).
  useEffect(() => {
    if (!canManage) return;
    let cancelled = false;
    browserApiFetch<PhotoAlbum[]>("/api/files/albums")
      .then((data) => { if (!cancelled) setOptions(data ?? []); })
      .catch(() => { if (!cancelled) setOptions([]); });
    return () => {
      cancelled = true;
    };
  }, [canManage]);

  async function add(album: PhotoAlbum) {
    if (!(await confirmAddToSharedAlbum(confirm, tShareRelease, album, 1))) return;
    await browserApiFetch(`/api/files/albums/${album.id}/items`, { method: "POST", body: JSON.stringify({ file_ids: [item.id] }) });
    onChange([...albums, { id: album.id, name: album.name, kind: album.kind, is_best: false }]);
    showToast(t("added", { album: album.name }), "success");
  }

  async function remove(album: FileAlbumRef) {
    await browserApiFetch(`/api/files/albums/${album.id}/items/remove`, { method: "POST", body: JSON.stringify({ file_ids: [item.id] }) });
    onChange(albums.filter((entry) => entry.id !== album.id));
    showToast(t("removed", { album: album.name }), "success");
  }

  async function run(action: () => Promise<void>) {
    if (busy) return;
    setBusy(true);
    try {
      await action();
    } catch (error) {
      showToast(error instanceof Error && error.message ? error.message : t("error"), "error");
    } finally {
      setBusy(false);
    }
  }

  function handleSelection(ids: string[]) {
    const current = new Set(albums.map((album) => album.id));
    const added = (options ?? []).find((album) => ids.includes(album.id) && !current.has(album.id));
    const removed = albums.find((album) => !ids.includes(album.id));
    if (added) void run(() => add(added));
    else if (removed) void run(() => remove(removed));
  }

  return (
    <section className="photo-viewer-section" aria-labelledby="pv-albums-title">
      <div className="photo-viewer-section-head">
        <h2 className="photo-viewer-section-title" id="pv-albums-title">{t("title")}</h2>
        {canManage ? (
          <SearchableMultiSelect<PhotoAlbum, string>
              className="photo-viewer-album-select"
              options={options ?? []}
              getId={(album) => album.id}
              getLabel={(album) => (album.is_shared ? t("sharedOption", { name: album.name }) : album.name)}
              values={albums.map((album) => album.id)}
              onChange={handleSelection}
              triggerLabel={t("add")}
              emptyLabel={options === null ? t("loading") : t("none")}
              disabled={busy}
            />
        ) : null}
      </div>
      {albums.length === 0 ? (
        <p className="photo-viewer-empty">{t("empty")}</p>
      ) : (
        <ul className="photo-viewer-chips">
          {albums.map((album) => (
            <li key={album.id} className="photo-viewer-chip">
              {album.name}
              {canManage ? (
                <button type="button" className="photo-viewer-chip-remove" aria-label={t("removeLabel", { album: album.name })} onClick={() => void run(() => remove(album))} disabled={busy}>
                  ×
                </button>
              ) : null}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function AnalysisSection({ item }: { item: FileOverviewItem }) {
  const t = useTranslations("photos.viewer");
  const hasFace = item.face_quality_score !== null;
  const face = (
    <PhotoMeter
      key="face"
      label={t("faceQualityLabel")}
      tone="face"
      value={item.face_analyzed_at === null ? null : item.face_quality_score !== null ? describeSharpness(item.face_quality_score, t) : t("noFaceDetected")}
      fraction={item.face_quality_score !== null ? sharpnessFraction(item.face_quality_score) : null}
      title={item.face_quality_score !== null ? t("faceRawTitle", { score: item.face_quality_score.toFixed(1) }) : undefined}
    />
  );
  return (
    <section className="photo-viewer-section" aria-labelledby="pv-analysis-title">
      <h2 className="photo-viewer-section-title" id="pv-analysis-title">{t("analysisSection")}</h2>
      {hasFace ? face : null}
      <PhotoMeter
        label={hasFace ? t("sharpnessFullLabel") : t("sharpnessLabel")}
        tone="sharpness"
        value={item.sharpness_score !== null ? describeSharpness(item.sharpness_score, t) : null}
        fraction={item.sharpness_score !== null ? sharpnessFraction(item.sharpness_score) : null}
        title={item.sharpness_score !== null ? t("sharpnessRawTitle", { score: item.sharpness_score.toFixed(1) }) : undefined}
      />
      <PhotoMeter
        label={t("exposureLabel")}
        tone="exposure"
        value={item.exposure_score !== null ? describeExposure(item.exposure_score, t) : null}
        fraction={item.exposure_score}
        title={item.exposure_score !== null ? t("exposureRawTitle", { percent: Math.round((1 - item.exposure_score) * 100) }) : undefined}
      />
      {hasFace ? null : face}
    </section>
  );
}

function PhotoMeter({ label, value, fraction, tone, title }: { label: string; value: string | null; fraction: number | null; tone: "sharpness" | "exposure" | "face"; title?: string }) {
  const t = useTranslations("photos.viewer");
  return (
    <div className="photo-meter-row" title={title}>
      <div className="photo-meter-label-row">
        <span className="photo-meter-label">{label}</span>
        <span className="photo-meter-value">{value ?? t("analysisPending")}</span>
      </div>
      <div className="photo-meter-bar">
        <div className={`photo-meter-fill photo-meter-fill-${tone}`} style={{ width: `${fraction !== null ? Math.round(fraction * 100) : 0}%` }} />
      </div>
    </div>
  );
}

function DetailsSection({ item, metadata, albums }: { item: FileOverviewItem; metadata: StoredFileMetadata | null; albums: FileAlbumRef[] }) {
  const t = useTranslations("photos.viewer");
  const locale = useLocale();
  const dimensions = metadata?.width && metadata?.height ? t("dimensionsValue", { width: metadata.width, height: metadata.height }) : null;
  const refParts = [albums[0]?.name, item.context_label].filter(Boolean);
  const uploaded = [formatDateTime(item.created_at, locale), metadata?.uploaded_by_name].filter(Boolean).join(" · ");
  return (
    <section className="photo-viewer-section" aria-labelledby="pv-details-title">
      <h2 className="photo-viewer-section-title" id="pv-details-title">{t("detailsSection")}</h2>
      <dl className="photo-viewer-details">
        {refParts.length > 0 ? (
          <div className="photo-viewer-details-wide">
            <dt>{t("refLabel")}</dt>
            <dd>{refParts.join(" · ")}</dd>
          </div>
        ) : null}
        <div className="photo-viewer-details-wide">
          <dt>{t("uploadedLabel")}</dt>
          <dd>{uploaded}</dd>
        </div>
        <div className="photo-viewer-details-wide">
          <dt>{t("locationLabel")}</dt>
          <dd>
            {metadata?.gps ? (
              <>
                {t("locationValue", { latitude: metadata.gps.latitude.toFixed(5), longitude: metadata.gps.longitude.toFixed(5) })}
                {metadata.gps.altitude_m !== null && metadata.gps.altitude_m !== undefined ? ` · ${t("altitudeValue", { meters: Math.round(metadata.gps.altitude_m) })}` : ""}
              </>
            ) : "—"}
          </dd>
        </div>
        <div>
          <dt>{t("dimensionsLabel")}</dt>
          <dd>{dimensions || "—"}</dd>
        </div>
        <div>
          <dt>{t("sizeLabel")}</dt>
          <dd>{item.file_size_bytes !== null && item.file_size_bytes !== undefined ? formatFileSize(item.file_size_bytes) : "—"}</dd>
        </div>
        <div>
          <dt>{t("cameraLabel")}</dt>
          <dd>{metadata?.exif_camera || "—"}</dd>
        </div>
        <div>
          <dt>{t("originLabel")}</dt>
          <dd>{item.origin_tag}</dd>
        </div>
      </dl>
    </section>
  );
}
