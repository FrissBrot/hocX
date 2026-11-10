"use client";

// Assets des Document Studio: Logos, Briefkopf-Bilder, Hintergründe, Wasserzeichen, Grafiken
// und Schriften. Hochladen (Virenscan im Backend), umbenennen, Kategorie ändern, löschen -
// verwendete Assets lassen sich nicht löschen (veröffentlichte Revisionen bleiben reproduzierbar).
// Zeigt, wo eine Datei verwendet wird, und führt gleiche Dateien zusammen (Gestaltung auf Abruf).

import { ChangeEvent, useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";

import { ActionMenu } from "@/components/ui/action-menu";
import { Badge } from "@/components/ui/badge";
import { EmptyState } from "@/components/ui/empty-state";
import { FilterTabs } from "@/components/ui/filter-tabs";
import { Modal } from "@/components/ui/modal";
import { useConfirm } from "@/contexts/confirm-context";
import { useToast } from "@/contexts/toast-context";
import { apiErrorMessage, AssetReference, Capabilities, DocumentAsset, studioApi } from "@/lib/documents/api";
import { Select } from "@/components/ui/select";

const CATEGORIES = ["logo", "letterhead", "background", "watermark", "graphic", "image", "font"];
// Gruppen der Übersicht: Logos, übrige Bilder (Fussbilder, Briefköpfe, Grafiken …), Schriften
const GROUPS = [
  { key: "logos", matches: (asset: DocumentAsset) => asset.category === "logo" },
  { key: "graphics", matches: (asset: DocumentAsset) => asset.kind === "image" && asset.category !== "logo" },
  { key: "fonts", matches: (asset: DocumentAsset) => asset.kind === "font" },
] as const;
type UsageFilter = "all" | "used" | "unused";

export function AssetLibrary({ capabilities }: { capabilities: Capabilities }) {
  const t = useTranslations("documentStudio");
  const toast = useToast();
  const confirm = useConfirm();
  const [assets, setAssets] = useState<DocumentAsset[] | null>(null);
  const [usage, setUsage] = useState<UsageFilter>("all");
  const [uploading, setUploading] = useState(false);
  const [editing, setEditing] = useState<DocumentAsset | null>(null);
  const [references, setReferences] = useState<{ asset: DocumentAsset; items: AssetReference[] } | null>(null);
  const imageInput = useRef<HTMLInputElement>(null);
  const fontInput = useRef<HTMLInputElement>(null);
  const canEdit = capabilities.manage_brand;

  const load = () => void studioApi.assets().then(setAssets).catch((error) => toast(apiErrorMessage(error, t("assets.loadFailed")), "error"));
  useEffect(load, []); // eslint-disable-line react-hooks/exhaustive-deps

  async function upload(event: ChangeEvent<HTMLInputElement>, kind: "image" | "font") {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    setUploading(true);
    try {
      await studioApi.uploadAsset(file, kind, kind === "font" ? "font" : "image");
      toast(t("assets.uploaded"), "success");
      load();
    } catch (error) {
      toast(apiErrorMessage(error, t("assets.uploadFailed")), "error");
    } finally {
      setUploading(false);
    }
  }

  const isUsed = (asset: DocumentAsset) => (asset.used_in ?? []).length > 0;
  const all = assets ?? [];
  const visible = all.filter((asset) => usage === "all" || (usage === "used") === isUsed(asset));
  // Überzählige Kopien gleicher Dateien (je Gruppe alle bis auf eine)
  const grouped = all.filter((asset) => asset.duplicate_group);
  const duplicates = grouped.length - new Set(grouped.map((asset) => asset.duplicate_group)).size;

  async function mergeDuplicates() {
    try {
      const result = await studioApi.mergeDuplicateAssets();
      toast(t("assets.merged", { count: result.removed }), result.removed ? "success" : "info");
      load();
    } catch (error) {
      toast(apiErrorMessage(error, t("common.actionFailed")), "error");
    }
  }

  return (
    <div className="grid">
      <div className="page-header">
        <div>
          <h1 className="page-title">{t("assets.title")}</h1>
          <p className="muted">{t("assets.description")}</p>
        </div>
        {canEdit && (
          <div className="studio-header-actions">
            <input ref={fontInput} type="file" hidden accept=".ttf,.otf" onChange={(event) => void upload(event, "font")} />
            <input ref={imageInput} type="file" hidden accept="image/png,image/jpeg,image/webp" onChange={(event) => void upload(event, "image")} />
            <button type="button" className="button-secondary" disabled={uploading} onClick={() => fontInput.current?.click()}>
              {t("assets.uploadFont")}
            </button>
            <button type="button" className="button-primary" disabled={uploading} onClick={() => imageInput.current?.click()}>
              {uploading ? t("assets.uploading") : t("assets.uploadImage")}
            </button>
          </div>
        )}
      </div>
      <div className="list-filter-row studio-asset-toolbar">
        <FilterTabs<UsageFilter>
          options={[
            { value: "all", label: t("assets.filter.all"), count: all.length },
            { value: "used", label: t("assets.filter.used"), count: all.filter(isUsed).length },
            { value: "unused", label: t("assets.filter.unused"), count: all.filter((asset) => !isUsed(asset)).length },
          ]}
          value={usage}
          onChange={setUsage}
        />
        {canEdit && duplicates > 0 && (
          <button type="button" className="button-secondary button-ghost" onClick={() => void mergeDuplicates()}>
            {t("assets.mergeDuplicates", { count: duplicates })}
          </button>
        )}
      </div>
      {assets !== null && visible.length === 0 && <EmptyState title={t("assets.emptyTitle")} description={canEdit ? t("assets.emptyUpload") : t("assets.emptyNoUpload")} icon="image" />}
      {GROUPS.map((group) => {
        const items = visible.filter(group.matches);
        if (items.length === 0) return null;
        return (
          <section key={group.key} className="studio-library-section" aria-labelledby={`studio-assets-${group.key}`}>
            <h2 id={`studio-assets-${group.key}`} className="studio-section-title">
              {t(`assets.group.${group.key}`)}
            </h2>
            <div className="studio-asset-grid">
              {items.map((asset) => (
                <article key={asset.id} className={isUsed(asset) ? "studio-asset studio-asset-card" : "studio-asset studio-asset-card studio-asset-unused"}>
                  {asset.kind === "image" ? (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img src={asset.content_url} alt="" loading="lazy" />
                  ) : (
                    <span className="studio-asset-font">Aa{/* i18n-ok: Schriftmuster, kein Text */}</span>
                  )}
                  <div className="studio-asset-meta">
                    <span className="studio-asset-name">{asset.font_family ?? asset.name}</span>
                    <span className="field-help">
                      {t(`assets.category.${asset.category}`)}
                      {asset.width_px ? ` · ${asset.width_px}×${asset.height_px}` : ""}
                    </span>
                    <span className="studio-card-badges">
                      {isUsed(asset) ? (
                        <Badge variant="success">{t("assets.usedIn", { name: (asset.used_in ?? [])[0], count: (asset.used_in ?? []).length - 1 })}</Badge>
                      ) : (
                        <Badge variant="neutral">{t("assets.notUsed")}</Badge>
                      )}
                      {(asset.duplicate_count ?? 0) > 1 && <Badge variant="warning">{t("assets.duplicates", { count: asset.duplicate_count ?? 0 })}</Badge>}
                    </span>
                  </div>
                  <ActionMenu
                    ariaLabel={t("assets.actionsFor", { name: asset.name })}
                    items={[
                      { label: t("assets.usage"), onClick: () => void studioApi.assetReferences(asset.id).then((items) => setReferences({ asset, items })) },
                      ...(canEdit
                        ? [
                            { label: t("assets.edit"), onClick: () => setEditing(asset) },
                            {
                              label: t("assets.delete"),
                              danger: true,
                              onClick: async () => {
                                if (!(await confirm({ message: t("assets.deleteConfirm", { name: asset.name }), tone: "danger", confirmLabel: t("assets.delete") }))) return;
                                try {
                                  await studioApi.deleteAsset(asset.id);
                                  toast(t("assets.deleted"), "success");
                                  load();
                                } catch (error) {
                                  toast(apiErrorMessage(error, t("common.actionFailed")), "error");
                                }
                              },
                            },
                          ]
                        : []),
                    ]}
                  />
                </article>
              ))}
            </div>
          </section>
        );
      })}
      <Modal className="studio-modal" open={!!editing} onClose={() => setEditing(null)} title={t("assets.editTitle")}>
        {editing && (
          <>
            <label className="field-stack">
              <span className="field-label">{t("assets.name")}</span>
              <input value={editing.name} maxLength={120} onChange={(event) => setEditing({ ...editing, name: event.target.value })} />
            </label>
            {editing.kind === "image" && (
              <label className="field-stack">
                <span className="field-label">{t("assets.categoryLabel")}</span>
                <Select value={editing.category} onChange={(event) => setEditing({ ...editing, category: event.target.value as DocumentAsset["category"] })}>
                  {CATEGORIES.filter((value) => value !== "font").map((value) => (
                    <option key={value} value={value}>
                      {t(`assets.category.${value}`)}
                    </option>
                  ))}
                </Select>
              </label>
            )}
            <div className="modal-actions">
              <button type="button" className="button-ghost" onClick={() => setEditing(null)}>
                {t("common.cancel")}
              </button>
              <button
                type="button"
                className="button-primary"
                onClick={async () => {
                  try {
                    await studioApi.updateAsset(editing.id, { name: editing.name, category: editing.category });
                    setEditing(null);
                    load();
                  } catch (error) {
                    toast(apiErrorMessage(error, t("common.actionFailed")), "error");
                  }
                }}
              >
                {t("common.save")}
              </button>
            </div>
          </>
        )}
      </Modal>
      <Modal className="studio-modal" open={!!references} onClose={() => setReferences(null)} title={t("assets.usageTitle", { name: references?.asset.name ?? "" })}>
        {references?.items.length ? (
          <ul className="studio-revision-list">
            {references.items.map((item) => (
              <li key={`${item.kind}-${item.id}`} className="studio-revision-item">
                {t(`assets.referenceKind.${item.kind}`)}: {item.name}
              </li>
            ))}
          </ul>
        ) : (
          <p className="muted">{t("assets.unused")}</p>
        )}
      </Modal>
    </div>
  );
}
