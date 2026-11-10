"use client";

// Bild aus den Document-Assets des Mandanten wählen (Logo, Briefkopf, Grafiken …); wer das
// Corporate Design verwalten darf, kann hier direkt hochladen. Reine Auswahl: ein Klick
// übernimmt das Bild und schliesst den Dialog.

import { ChangeEvent, useRef, useState } from "react";
import { useTranslations } from "next-intl";

import { EmptyState } from "@/components/ui/empty-state";
import { FilterTabs } from "@/components/ui/filter-tabs";
import { Modal } from "@/components/ui/modal";
import { useToast } from "@/contexts/toast-context";
import { apiErrorMessage, DocumentAsset, studioApi } from "@/lib/documents/api";

type Props = {
  open: boolean;
  onClose: () => void;
  assets: DocumentAsset[];
  onAssetsChange: (assets: DocumentAsset[]) => void;
  onPick: (asset: DocumentAsset) => void;
  canUpload: boolean;
  kind?: "image" | "font";
  defaultCategory?: string;
};

const IMAGE_CATEGORIES = ["logo", "letterhead", "background", "watermark", "graphic", "image"];

export function AssetPicker({ open, onClose, assets, onAssetsChange, onPick, canUpload, kind = "image", defaultCategory = "image" }: Props) {
  const t = useTranslations("documentStudio");
  const toast = useToast();
  const [category, setCategory] = useState("all");
  const [uploading, setUploading] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const visible = assets.filter((asset) => asset.kind === kind && (category === "all" || asset.category === category));

  async function upload(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    setUploading(true);
    try {
      const asset = await studioApi.uploadAsset(file, kind, kind === "image" ? (category === "all" ? defaultCategory : category) : "font");
      onAssetsChange([asset, ...assets]);
      toast(t("assets.uploaded"), "success");
    } catch (error) {
      toast(apiErrorMessage(error, t("assets.uploadFailed")), "error");
    } finally {
      setUploading(false);
    }
  }

  return (
    <Modal className="studio-modal" open={open} onClose={onClose} title={kind === "image" ? t("assets.pickImage") : t("assets.pickFont")} size="wide">
      {kind === "image" && (
        <FilterTabs variant="chips" options={[{ value: "all", label: t("assets.categoryAll") }, ...IMAGE_CATEGORIES.map((value) => ({ value, label: t(`assets.category.${value}`) }))]} value={category} onChange={setCategory} />
      )}
      {visible.length === 0 ? (
        <EmptyState title={t("assets.emptyTitle")} description={canUpload ? t("assets.emptyUpload") : t("assets.emptyNoUpload")} icon="image" />
      ) : (
        <div className="studio-asset-grid">
          {visible.map((asset) => (
            <button key={asset.id} type="button" className="studio-asset" onClick={() => { onPick(asset); onClose(); }}>
              {asset.kind === "image" ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img src={asset.content_url} alt="" loading="lazy" />
              ) : (
                <span className="studio-asset-font">Aa{/* i18n-ok: Schriftmuster, kein Text */}</span>
              )}
              <span className="studio-asset-name">{asset.font_family ?? asset.name}</span>
            </button>
          ))}
        </div>
      )}
      {canUpload && (
        <div className="modal-actions">
          <input ref={input} type="file" hidden accept={kind === "image" ? "image/png,image/jpeg,image/webp" : ".ttf,.otf"} onChange={(event) => void upload(event)} />
          <button type="button" className="button-secondary" disabled={uploading} onClick={() => input.current?.click()}>
            {uploading ? t("assets.uploading") : t("assets.upload")}
          </button>
        </div>
      )}
    </Modal>
  );
}
