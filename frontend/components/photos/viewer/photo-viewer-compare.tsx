"use client";

import { useRef } from "react";
import { useTranslations } from "next-intl";

import { FilterTabs } from "@/components/ui/filter-tabs";
import { SegmentedControl } from "@/components/ui/segmented-control";
import { usePopupEscape } from "@/lib/hooks/use-popup-escape";
import { browserApiBaseUrl } from "@/lib/api/client";
import type { FileOverviewItem } from "@/types/api";
import { PhotoActionIcon } from "../photo-action-icon";
import {
  CompareDecision,
  CompareDecisions,
  compareSuggestion,
  compareSummary,
  exposureLevel,
  isDeletable,
  keepAllDecisions,
  setDecision,
  sharpnessFraction,
  sharpnessLevel,
  toggleDecision,
  ViewerGroup,
} from "./viewer-logic";

/** Vergleichsmodus der Foto-Ansicht: Raster einer Duplikat- oder Ähnlich-Gruppe, Behalten/Löschen
 * je Bild (Vorschlag vorausgefüllt), nicht löschbare Bilder bleiben. «Anwenden» legt die
 * gewählten Bilder in den Papierkorb und markiert die Gruppe als geprüft (photo-viewer.tsx). */
export function PhotoViewerCompare({
  groups,
  active,
  currentId,
  decisions,
  busy,
  onSelectGroup,
  onDecisions,
  onExit,
  onApply,
}: {
  groups: ViewerGroup[];
  active: ViewerGroup;
  currentId: string;
  decisions: CompareDecisions;
  busy: boolean;
  onSelectGroup: (key: string) => void;
  onDecisions: (decisions: CompareDecisions) => void;
  onExit: () => void;
  onApply: () => void;
}) {
  const t = useTranslations("photos.viewer.compare");
  const tv = useTranslations("photos.viewer");
  const rootRef = useRef<HTMLDivElement>(null);
  // Escape verlässt zuerst den Vergleich (liegt im Viewer, also über ihm im Escape-Stapel).
  usePopupEscape(true, onExit, rootRef);
  const summary = compareSummary(active.group, decisions);

  return (
    <div ref={rootRef} className="photo-viewer-compare" role="region" aria-label={t("regionLabel")}>
      <div className="photo-viewer-compare-head">
        <div className="photo-viewer-compare-intro">
          <button type="button" className="button-ghost photo-viewer-back" onClick={onExit}>
            <PhotoActionIcon name="back" />
            {t("back")}
          </button>
          {groups.length > 1 ? (
            <FilterTabs<string>
              value={active.key}
              onChange={onSelectGroup}
              options={groups.map((entry) => ({
                value: entry.key,
                label: entry.kind === "duplicate"
                  ? t("tabDuplicates", { count: entry.group.images.length })
                  : t("tabSimilar", { count: entry.group.images.length }),
              }))}
            />
          ) : (
            <h2 className="photo-viewer-compare-title">
              {active.kind === "duplicate" ? t("tabDuplicates", { count: active.group.images.length }) : t("tabSimilar", { count: active.group.images.length })}
            </h2>
          )}
          <p className="photo-viewer-compare-text">{active.kind === "duplicate" ? t("introDuplicates") : t("introSimilar")}</p>
        </div>
        <div className="photo-viewer-compare-quick">
          <button type="button" className="button-secondary" onClick={() => onDecisions(keepAllDecisions(active.group))} disabled={busy}>
            {t("keepAll")}
          </button>
          <button type="button" className="button-secondary photo-viewer-compare-suggest" onClick={() => onDecisions(compareSuggestion(active.group))} disabled={busy}>
            <PhotoActionIcon name="star" />
            {t("keepBest")}
          </button>
        </div>
      </div>

      <div className="photo-viewer-compare-scroll">
        <ul className="photo-viewer-compare-grid">
          {active.group.images.map((image) => (
            <CompareCard
              key={image.id}
              image={image}
              isBest={image.id === active.group.best_id}
              isCurrent={image.id === currentId}
              decision={decisions[image.id] ?? "keep"}
              disabled={busy}
              onToggle={() => onDecisions(toggleDecision(decisions, image))}
              onDecide={(decision) => onDecisions(setDecision(decisions, image, decision))}
              tv={tv}
            />
          ))}
        </ul>
      </div>

      <div className="photo-viewer-compare-foot">
        <p className="photo-viewer-compare-summary" aria-live="polite">
          <span className="photo-viewer-dot photo-viewer-dot-keep" aria-hidden="true" />
          {t("summaryKeep", { count: summary.keep })}
          <span className="photo-viewer-dot photo-viewer-dot-trash" aria-hidden="true" />
          {t("summaryTrash", { count: summary.trash })}
          <span className="photo-viewer-compare-hint">{t("toggleHint")}</span>
        </p>
        <div className="photo-viewer-compare-actions">
          <button type="button" className="button-ghost" onClick={onExit} disabled={busy}>{t("cancel")}</button>
          <button type="button" className={summary.trash > 0 ? "button-danger" : "button-primary"} onClick={onApply} disabled={busy}>
            {summary.trash > 0 ? t("applyTrash", { count: summary.trash }) : t("applyReviewed")}
          </button>
        </div>
      </div>
    </div>
  );
}

type TFunc = (key: string, values?: Record<string, string | number | Date>) => string;

function CompareCard({
  image,
  isBest,
  isCurrent,
  decision,
  disabled,
  onToggle,
  onDecide,
  tv,
}: {
  image: FileOverviewItem;
  isBest: boolean;
  isCurrent: boolean;
  decision: CompareDecision;
  disabled: boolean;
  onToggle: () => void;
  onDecide: (decision: CompareDecision) => void;
  tv: TFunc;
}) {
  const t = useTranslations("photos.viewer.compare");
  const deletable = isDeletable(image);
  const trash = deletable && decision === "trash";
  const thumbnail = `${browserApiBaseUrl}${image.thumbnail_url ?? image.content_url}`;
  const meters = [
    image.sharpness_score !== null
      ? { key: "sharpness", label: tv("sharpnessLabel"), fraction: sharpnessFraction(image.sharpness_score), value: tv(`sharpnessLevels.${sharpnessLevel(image.sharpness_score)}`), weak: image.sharpness_score < 50 }
      : null,
    image.exposure_score !== null
      ? { key: "exposure", label: tv("exposureLabel"), fraction: image.exposure_score, value: tv(`exposureLevels.${exposureLevel(image.exposure_score)}`), weak: image.exposure_score < 0.85 }
      : null,
  ].filter((meter): meter is NonNullable<typeof meter> => meter !== null);

  return (
    <li className={`photo-viewer-card${trash ? " photo-viewer-card-trash" : isBest ? " photo-viewer-card-best" : ""}`}>
      {deletable ? (
        <button
          type="button"
          className="photo-viewer-card-image"
          aria-pressed={trash}
          aria-label={trash ? t("toggleToKeep", { name: image.original_name }) : t("toggleToTrash", { name: image.original_name })}
          onClick={onToggle}
          disabled={disabled}
        >
          <CardImage src={thumbnail} alt="" />
          <CardBadges isBest={isBest} isCurrent={isCurrent} trash={trash} />
        </button>
      ) : (
        <div className="photo-viewer-card-image">
          <CardImage src={thumbnail} alt={image.original_name} />
          <CardBadges isBest={isBest} isCurrent={isCurrent} trash={false} />
        </div>
      )}
      <div className="photo-viewer-card-body">
        <div className="photo-viewer-card-title">
          <span className="photo-viewer-card-name">{image.original_name}</span>
        </div>
        {meters.map((meter) => (
          <div key={meter.key} className="photo-viewer-card-meter">
            <span>{meter.label}</span>
            <span className="photo-viewer-card-bar"><span className={`photo-viewer-card-fill photo-viewer-card-fill-${meter.key}`} style={{ width: `${Math.round(meter.fraction * 100)}%` }} /></span>
            <span className={meter.weak ? "photo-viewer-card-weak" : undefined}>{meter.value}</span>
          </div>
        ))}
        <span className="photo-viewer-card-origin">{[image.origin_tag, image.context_label].filter(Boolean).join(" · ")}</span>
        {deletable ? (
          <SegmentedControl<CompareDecision>
            className="photo-viewer-card-decision"
            aria-label={t("decisionLabel", { name: image.original_name })}
            value={trash ? "trash" : "keep"}
            onChange={onDecide}
            options={[
              { value: "keep", label: t("keep"), disabled },
              { value: "trash", label: t("trash"), disabled },
            ]}
          />
        ) : (
          <p className="photo-viewer-card-locked">
            <PhotoActionIcon name="lock" />
            {t("locked", { origin: image.origin_tag })}
          </p>
        )}
      </div>
    </li>
  );
}

function CardImage({ src, alt }: { src: string; alt: string }) {
  return <img src={src} alt={alt} loading="lazy" decoding="async" draggable={false} />;
}

function CardBadges({ isBest, isCurrent, trash }: { isBest: boolean; isCurrent: boolean; trash: boolean }) {
  const t = useTranslations("photos.viewer.compare");
  return (
    <>
      <span className="photo-viewer-card-badges">
        {isBest ? <span className="photo-viewer-badge-best">{t("bestChoice")}</span> : null}
        {isCurrent ? <span className="photo-viewer-badge-muted">{t("opened")}</span> : null}
      </span>
      {trash ? <span className="photo-viewer-card-trash-label"><PhotoActionIcon name="delete" />{t("trashLabel")}</span> : null}
    </>
  );
}
