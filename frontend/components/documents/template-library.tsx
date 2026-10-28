"use client";

// Dokumentvorlagen (Gestaltung auf Abruf): nur die eigenen und übernommenen Vorlagen des Vereins,
// gruppiert in Sitzungsdokumente (Protokoll, Einladung, Traktandenliste) und weitere Dokumente.
// Alles Mitgelieferte liegt im Katalog und wird erst beim Hinzufügen als genau eine Vorlage
// übernommen; fehlt ein Dokumenttyp, nutzt der Export den Katalog-Standard ohne Kopie. Nicht
// verwendete Vorlagen lassen sich gesammelt archivieren («Aufräumen»).

import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import Link from "next/link";
import type { Route } from "next";
import { useRouter } from "next/navigation";

import { AssignmentsModal } from "@/components/documents/assignments-modal";
import { catalogItems, originLabel, ownTemplates, SESSION_CATEGORY } from "@/components/documents/catalog";
import { CatalogModal } from "@/components/documents/catalog-modal";
import { CleanupModal } from "@/components/documents/cleanup-modal";
import { RevisionsModal } from "@/components/documents/revisions-modal";
import { templateDescription, templateDisplayName } from "@/components/documents/studio-labels";
import { TemplateCreateModal } from "@/components/documents/template-create-modal";
import { TemplatePreviewModal } from "@/components/documents/template-preview-modal";
import { ActionMenu, ActionMenuItem } from "@/components/ui/action-menu";
import { Badge } from "@/components/ui/badge";
import { Modal } from "@/components/ui/modal";
import { SearchInput } from "@/components/ui/search-input";
import { StatusBanner } from "@/components/ui/status-banner";
import { useConfirm } from "@/contexts/confirm-context";
import { useToast } from "@/contexts/toast-context";
import { apiErrorMessage, Brand, Capabilities, DesignExample, DocumentTemplateInfo, DocumentTypeInfo, studioApi } from "@/lib/documents/api";

type Props = { capabilities: Capabilities };
type Dialog = { kind: "catalog" | "create"; documentType?: string | null } | { kind: "cleanup" } | null;

export function TemplateLibrary({ capabilities }: Props) {
  const t = useTranslations("documentStudio");
  const router = useRouter();
  const toast = useToast();
  const confirm = useConfirm();
  // Alle sichtbaren Vorlagen inkl. Katalog (Systemvorlagen); angezeigt werden nur die eigenen
  const [templates, setTemplates] = useState<DocumentTemplateInfo[] | null>(null);
  const [types, setTypes] = useState<DocumentTypeInfo[]>([]);
  const [categories, setCategories] = useState<string[]>([]);
  const [designs, setDesigns] = useState<DesignExample[]>([]);
  const [brands, setBrands] = useState<Brand[]>([]);
  const [query, setQuery] = useState("");
  const [showArchived, setShowArchived] = useState(false);
  const [error, setError] = useState("");
  const [dialog, setDialog] = useState<Dialog>(null);
  const [assignmentsOpen, setAssignmentsOpen] = useState(false);
  const [preview, setPreview] = useState<DocumentTemplateInfo | null>(null);
  const [revisionsOf, setRevisionsOf] = useState<DocumentTemplateInfo | null>(null);
  const [renaming, setRenaming] = useState<DocumentTemplateInfo | null>(null);
  const [newName, setNewName] = useState("");

  const load = useCallback(() => {
    studioApi
      .listTemplates({ includeArchived: showArchived })
      .then((loaded) => {
        setTemplates(loaded ?? []);
        setError("");
      })
      .catch((reason) => setError(apiErrorMessage(reason, t("library.loadFailed"))));
    // t/toast sind während der Lebensdauer der Komponente unveränderlich
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [showArchived]);

  useEffect(() => load(), [load]);
  useEffect(() => {
    void studioApi.catalog().then((catalog) => {
      setTypes(catalog.document_types);
      setCategories(catalog.categories);
    });
    void studioApi.listExamples().then((loaded) => setDesigns(loaded ?? [])).catch(() => setDesigns([]));
    void studioApi.brands().then((loaded) => setBrands(loaded ?? [])).catch(() => setBrands([]));
  }, []);

  const defaultBrand = brands.find((brand) => brand.is_default) ?? null;
  const brandVersion = defaultBrand ? `${defaultBrand.id}:${defaultBrand.revision}` : "none";
  const own = useMemo(() => ownTemplates(templates ?? []), [templates]);
  const catalog = useMemo(() => catalogItems(t, templates ?? [], designs, brandVersion), [t, templates, designs, brandVersion]);
  const cleanup = useMemo(() => own.filter((item) => item.cleanup_candidate), [own]);
  const sessionTypes = useMemo(() => types.filter((type) => type.category === SESSION_CATEGORY), [types]);
  const otherTypes = useMemo(() => types.filter((type) => type.category !== SESSION_CATEGORY), [types]);

  const groups = useMemo(() => {
    const needle = query.trim().toLowerCase();
    const matches = (item: DocumentTemplateInfo) =>
      !needle || `${templateDisplayName(t, item)} ${templateDescription(t, item)} ${t(`docType.${item.document_type}`)}`.toLowerCase().includes(needle);
    return [
      { key: "session", groupTypes: sessionTypes },
      { key: "other", groupTypes: otherTypes },
    ].map(({ key, groupTypes }) => {
      const keys = new Set(groupTypes.map((type) => type.key));
      const items = own.filter((item) => keys.has(item.document_type) && matches(item));
      const covered = new Set(own.filter((item) => item.status === "active").map((item) => item.document_type));
      const missing = groupTypes.filter((type) => !covered.has(type.key) && catalog.some((entry) => entry.documentType === type.key));
      return { key, groupTypes, items, missing };
    });
  }, [own, query, sessionTypes, otherTypes, catalog, t]);

  // Katalog-Standard eines Dokumenttyps, solange der Verein keine eigene Vorlage hat
  function catalogDefaultName(documentType: string): string | null {
    const fallback = (templates ?? []).find((item) => item.origin === "system" && item.document_type === documentType && item.is_default);
    return fallback ? templateDisplayName(t, fallback) : null;
  }

  function gapHint(missing: DocumentTypeInfo[]): string {
    if (missing.length === 0) return t("library.gapNone");
    if (missing.length === 1) {
      const fallback = catalogDefaultName(missing[0].key);
      if (fallback) return t("library.gapOne", { type: t(`docType.${missing[0].key}`), name: fallback });
    }
    const names = missing.slice(0, 4).map((type) => t(`docType.${type.key}`));
    return missing.length > 4 ? t("library.gapMore", { types: names.join(", ") }) : names.join(", ");
  }

  function usageText(item: DocumentTemplateInfo): string {
    const type = t(`docType.${item.document_type}`);
    if (sessionTypes.some((entry) => entry.key === item.document_type)) return t("library.usageSessions", { type, count: (item.used_in ?? []).length });
    return t("library.usageExports", { type, count: item.export_count ?? 0 });
  }

  async function run(action: () => Promise<unknown>, success: string) {
    try {
      await action();
      toast(success, "success");
      load();
    } catch (reason) {
      toast(apiErrorMessage(reason, t("common.actionFailed")), "error");
    }
  }

  async function duplicate(item: DocumentTemplateInfo) {
    try {
      const copy = await studioApi.duplicateTemplate(item.id, t("library.copyName", { name: templateDisplayName(t, item) }));
      toast(t("library.duplicated"), "success");
      router.push(`/documents/templates/${copy.id}`);
    } catch (reason) {
      toast(apiErrorMessage(reason, t("common.actionFailed")), "error");
    }
  }

  function actions(item: DocumentTemplateInfo): ActionMenuItem[] {
    const items: ActionMenuItem[] = [{ label: t("library.preview"), onClick: () => setPreview(item) }];
    if (item.editable) items.push({ label: t("library.edit"), onClick: () => router.push(`/documents/templates/${item.id}`) });
    if (capabilities.edit_templates) items.push({ label: t("library.duplicate"), onClick: () => void duplicate(item) });
    if (item.editable) {
      items.push({ label: t("library.rename"), onClick: () => { setRenaming(item); setNewName(item.name); } });
      items.push({ label: t("library.revisions"), onClick: () => setRevisionsOf(item) });
    }
    if (capabilities.publish_templates && item.published_revision && item.status === "active" && !item.is_default) {
      items.push({
        label: t("library.setDefault"),
        onClick: () => void run(() => studioApi.setAssignment({ document_type: item.document_type, template_id: item.id }), t("library.defaultSet")),
      });
    }
    if (capabilities.publish_templates && item.editable) {
      items.push(
        item.status === "archived"
          ? { label: t("library.unarchive"), onClick: () => void run(() => studioApi.archive(item.id, false), t("library.unarchived")) }
          : { label: t("library.archive"), onClick: () => void run(() => studioApi.archive(item.id, true), t("library.archived")) }
      );
      items.push({
        label: t("library.delete"),
        danger: true,
        onClick: async () => {
          if (await confirm({ message: t("library.deleteConfirm", { name: item.name }), tone: "danger", confirmLabel: t("library.delete") })) {
            await run(() => studioApi.deleteTemplate(item.id), t("library.deleted"));
          }
        },
      });
    }
    return items;
  }

  return (
    <div className="grid">
      <div className="page-header">
        <div>
          <h1 className="page-title">{t("library.documentsTitle")}</h1>
          <p className="muted">{t("library.documentsDescription")}</p>
        </div>
        <div className="studio-header-actions">
          <Link href="/documents/exports" className="button-secondary">
            {t("library.exportHistory")}
          </Link>
          {capabilities.publish_templates && (
            <button type="button" className="button-secondary" onClick={() => setAssignmentsOpen(true)}>
              {t("assignments.open")}
            </button>
          )}
          <button type="button" className="button-secondary" onClick={() => setDialog({ kind: "catalog" })}>
            {t("catalog.open")}
          </button>
          {capabilities.edit_templates && (
            <button type="button" className="button-primary" onClick={() => setDialog({ kind: "create" })}>
              {t("library.create")}
            </button>
          )}
        </div>
      </div>

      {cleanup.length > 0 && (
        <div className="studio-cleanup-banner" role="status">
          <div className="studio-cleanup-banner-text">
            <strong>{t("cleanup.bannerTitle", { count: cleanup.length })}</strong>
            <span>{t("cleanup.bannerText")}</span>
          </div>
          <button type="button" className="button-secondary" onClick={() => setDialog({ kind: "cleanup" })}>
            {t("cleanup.open")}
          </button>
        </div>
      )}

      <div className="list-filter-row">
        <SearchInput value={query} onChange={setQuery} placeholder={t("library.search")} />
        <label className="studio-inline-check">
          <input type="checkbox" checked={showArchived} onChange={(event) => setShowArchived(event.target.checked)} />
          <span>{t("library.showArchived")}</span>
        </label>
      </div>

      {error && <StatusBanner tone="error" message={error} />}
      {templates === null && !error && <p className="muted">{t("common.loading")}</p>}

      {templates !== null &&
        groups.map((group) => (
          <section key={group.key} className="studio-library-section" aria-labelledby={`studio-group-${group.key}`}>
            <div className="studio-library-heading">
              <h2 id={`studio-group-${group.key}`} className="studio-section-title">
                {t(`library.group.${group.key}.title`)}
              </h2>
              <span className="field-help">{t(`library.group.${group.key}.help`)}</span>
            </div>
            <div className="studio-gallery">
              {group.items.map((item) => {
                const origin = originLabel(t, item);
                return (
                  <article key={item.id} className={`studio-card${item.status === "archived" ? " studio-card-archived" : ""}${item.is_default ? " studio-card-default" : ""}`}>
                    <button type="button" className="studio-card-preview" onClick={() => setPreview(item)} aria-label={t("library.previewOf", { name: templateDisplayName(t, item) })}>
                      {/* eslint-disable-next-line @next/next/no-img-element */}
                      <img src={studioApi.thumbnailUrl(item.id, `${(item.draft_revision ?? item.published_revision)?.id ?? item.updated_at}:${brandVersion}`)} alt="" loading="lazy" />
                    </button>
                    <div className="studio-card-body">
                      <div className="studio-card-title-row">
                        <h3 className="studio-card-title">{templateDisplayName(t, item)}</h3>
                        <ActionMenu items={actions(item)} ariaLabel={t("library.actionsFor", { name: templateDisplayName(t, item) })} />
                      </div>
                      <p className="studio-card-description">{usageText(item)}</p>
                      {(item.used_in ?? []).length > 0 ? (
                        <div className="studio-card-usage">
                          {(item.used_in ?? []).map((ref) => (
                            <Link key={ref.id} href={`/templates/${ref.id}` as Route} className="studio-card-usage-chip">
                              {ref.name}
                            </Link>
                          ))}
                        </div>
                      ) : null}
                      <div className="studio-card-badges">
                        <Badge variant={origin.fromCatalog ? "neutral" : "info"}>{origin.label}</Badge>
                        {item.is_default && <Badge variant="success" dot>{t("library.default")}</Badge>}
                        {item.update_revision_no ? <Badge variant="info">{t("library.update", { revision: item.update_revision_no })}</Badge> : null}
                        {item.draft_revision && item.editable && <Badge variant="warning">{t("library.draft")}</Badge>}
                        {!item.published_revision && <Badge variant="warning">{t("library.unpublished")}</Badge>}
                        {item.status === "archived" && <Badge variant="neutral">{t("library.archivedBadge")}</Badge>}
                      </div>
                    </div>
                  </article>
                );
              })}
              {!query.trim() && (
                <button
                  type="button"
                  className="studio-gap-card"
                  onClick={() => setDialog({ kind: "catalog", documentType: group.missing[0]?.key ?? group.groupTypes[0]?.key ?? null })}
                >
                  <span className="studio-gap-plus" aria-hidden="true">+{/* i18n-ok: Symbol */}</span>
                  <span className="studio-gap-title">{t("library.addFromCatalog")}</span>
                  <span className="field-help">{gapHint(group.missing)}</span>
                </button>
              )}
            </div>
          </section>
        ))}

      {dialog?.kind === "catalog" && (
        <CatalogModal
          open
          onClose={() => setDialog(null)}
          items={catalog}
          types={types}
          categories={categories}
          initialType={dialog.documentType}
          canAdopt={capabilities.edit_templates}
          canBrand={capabilities.manage_brand}
          onAdopted={load}
        />
      )}
      {dialog?.kind === "create" && (
        <TemplateCreateModal
          open
          onClose={() => setDialog(null)}
          types={types}
          categories={categories}
          templates={own}
          catalog={catalog}
          brands={brands}
          canBrand={capabilities.manage_brand}
          initialType={dialog.documentType}
          onCreated={(created) => router.push(`/documents/templates/${created.id}`)}
        />
      )}
      {dialog?.kind === "cleanup" && (
        <CleanupModal
          open
          onClose={() => setDialog(null)}
          candidates={cleanup}
          onDone={() => {
            setDialog(null);
            load();
          }}
        />
      )}
      {assignmentsOpen && <AssignmentsModal open={assignmentsOpen} onClose={() => { setAssignmentsOpen(false); load(); }} types={types} templates={templates ?? []} />}
      {preview && <TemplatePreviewModal template={preview} onClose={() => setPreview(null)} />}
      {revisionsOf && <RevisionsModal template={revisionsOf} onClose={() => setRevisionsOf(null)} onRestored={() => router.push(`/documents/templates/${revisionsOf.id}`)} />}
      <Modal className="studio-modal" open={!!renaming} onClose={() => setRenaming(null)} title={t("library.renameTitle")}>
        <label className="field-stack">
          <span className="field-label">{t("library.name")}</span>
          <input value={newName} maxLength={160} onChange={(event) => setNewName(event.target.value)} autoFocus />
        </label>
        <div className="modal-actions">
          <button type="button" className="button-ghost" onClick={() => setRenaming(null)}>
            {t("common.cancel")}
          </button>
          <button
            type="button"
            className="button-primary"
            disabled={!newName.trim()}
            onClick={async () => {
              const target = renaming;
              setRenaming(null);
              if (target) await run(() => studioApi.updateTemplate(target.id, { name: newName.trim() }), t("library.renamed"));
            }}
          >
            {t("common.save")}
          </button>
        </div>
      </Modal>
    </div>
  );
}
