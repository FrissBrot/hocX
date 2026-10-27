"use client";

// Template Library: alle Vorlagen des Mandanten und von hocX als Galerie. Suchen, nach
// Kategorie filtern, Vorschau öffnen, erstellen, duplizieren, umbenennen, bearbeiten,
// veröffentlichen, archivieren, als Standard festlegen, Revisionen vergleichen/wiederherstellen.
// ``scope``: «documents» = weitere Dokumente (Todo-Liste, Termine, Briefe …), «session» =
// Standardgestaltung der Sitzungsdokumente (Protokoll, Einladung, Traktandenliste); Gestaltungen,
// die allein einer Sitzungsvorlage gehören, erscheinen nur in deren Editor.

import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import Link from "next/link";
import { useRouter } from "next/navigation";

import { AssignmentsModal } from "@/components/documents/assignments-modal";
import { RevisionsModal } from "@/components/documents/revisions-modal";
import { templateDescription, templateDisplayName } from "@/components/documents/studio-labels";
import { TemplateCreateModal } from "@/components/documents/template-create-modal";
import { TemplatePreviewModal } from "@/components/documents/template-preview-modal";
import { ActionMenu, ActionMenuItem } from "@/components/ui/action-menu";
import { Badge } from "@/components/ui/badge";
import { EmptyState } from "@/components/ui/empty-state";
import { FilterTabs } from "@/components/ui/filter-tabs";
import { Modal } from "@/components/ui/modal";
import { SearchInput } from "@/components/ui/search-input";
import { StatusBanner } from "@/components/ui/status-banner";
import { useConfirm } from "@/contexts/confirm-context";
import { useToast } from "@/contexts/toast-context";
import { apiErrorMessage, Capabilities, DocumentTemplateInfo, DocumentTypeInfo, studioApi } from "@/lib/documents/api";

type Props = { capabilities: Capabilities; scope?: "documents" | "session" };

export function TemplateLibrary({ capabilities, scope = "documents" }: Props) {
  const t = useTranslations("documentStudio");
  const router = useRouter();
  const toast = useToast();
  const confirm = useConfirm();
  const [templates, setTemplates] = useState<DocumentTemplateInfo[] | null>(null);
  const [types, setTypes] = useState<DocumentTypeInfo[]>([]);
  const [categories, setCategories] = useState<string[]>([]);
  const [category, setCategory] = useState("all");
  const [query, setQuery] = useState("");
  const [showArchived, setShowArchived] = useState(false);
  const [error, setError] = useState("");
  const [createOpen, setCreateOpen] = useState(false);
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
  }, []);

  const sessionTypes = useMemo(() => new Set(types.filter((type) => type.needs_protocol).map((type) => type.key)), [types]);
  const scopeTypes = useMemo(() => types.filter((type) => (scope === "session") === sessionTypes.has(type.key)), [types, scope, sessionTypes]);
  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return (templates ?? []).filter((item) => {
      if ((scope === "session") !== sessionTypes.has(item.document_type)) return false;
      if (item.session_template_id) return false;
      if (category !== "all" && item.category !== category) return false;
      if (!needle) return true;
      const haystack = `${templateDisplayName(t, item)} ${templateDescription(t, item)} ${t(`docType.${item.document_type}`)}`.toLowerCase();
      return haystack.includes(needle);
    });
    // t/toast sind während der Lebensdauer der Komponente unveränderlich
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [templates, category, query, scope, sessionTypes]);

  const byType = useMemo(() => {
    const groups = new Map<string, DocumentTemplateInfo[]>();
    for (const item of filtered) groups.set(item.document_type, [...(groups.get(item.document_type) ?? []), item]);
    return scopeTypes.filter((type) => groups.has(type.key)).map((type) => ({ type, items: groups.get(type.key) ?? [] }));
  }, [filtered, scopeTypes]);
  const scopeCategories = useMemo(() => categories.filter((key) => scopeTypes.some((type) => type.category === key)), [categories, scopeTypes]);

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
    if (capabilities.edit_templates) items.push({ label: item.origin === "system" ? t("library.customize") : t("library.duplicate"), onClick: () => void duplicate(item) });
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
        {scope === "session" ? (
          <div>
            <h1 className="page-title">{t("library.sessionTitle")}</h1>
            <p className="muted">{t("library.sessionDescription")}</p>
          </div>
        ) : (
          <div>
            <h1 className="page-title">{t("library.documentsTitle")}</h1>
            <p className="muted">{t("library.documentsDescription")}</p>
          </div>
        )}
        <div className="studio-header-actions">
          <Link href="/documents/exports" className="button-secondary">
            {t("library.exportHistory")}
          </Link>
          {capabilities.publish_templates && (
            <button type="button" className="button-secondary" onClick={() => setAssignmentsOpen(true)}>
              {t("assignments.open")}
            </button>
          )}
          {capabilities.edit_templates && (
            <button type="button" className="button-primary" onClick={() => setCreateOpen(true)}>
              {t("library.create")}
            </button>
          )}
        </div>
      </div>

      <div className="list-filter-row">
        <FilterTabs
          variant="chips"
          options={[{ value: "all", label: t("category.all") }, ...scopeCategories.map((key) => ({ value: key, label: t(`category.${key}`) }))]}
          value={category}
          onChange={setCategory}
        />
        <SearchInput value={query} onChange={setQuery} placeholder={t("library.search")} />
        <label className="studio-inline-check">
          <input type="checkbox" checked={showArchived} onChange={(event) => setShowArchived(event.target.checked)} />
          <span>{t("library.showArchived")}</span>
        </label>
      </div>

      {error && <StatusBanner tone="error" message={error} />}
      {templates === null && !error && <p className="muted">{t("common.loading")}</p>}
      {templates !== null && byType.length === 0 && <EmptyState title={t("library.emptyTitle")} description={t("library.emptyDescription")} />}

      {byType.map(({ type, items }) => (
        <section key={type.key} className="studio-library-section" aria-labelledby={`studio-type-${type.key}`}>
          <h2 id={`studio-type-${type.key}`} className="studio-section-title">
            {t(`docType.${type.key}`)}
          </h2>
          <div className="studio-gallery">
            {items.map((item) => (
              <article key={item.id} className={item.status === "archived" ? "studio-card studio-card-archived" : "studio-card"}>
                <button type="button" className="studio-card-preview" onClick={() => setPreview(item)} aria-label={t("library.previewOf", { name: templateDisplayName(t, item) })}>
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img src={studioApi.thumbnailUrl(item.id, (item.draft_revision ?? item.published_revision)?.id ?? item.updated_at)} alt="" loading="lazy" />
                </button>
                <div className="studio-card-body">
                  <div className="studio-card-title-row">
                    <h3 className="studio-card-title">{templateDisplayName(t, item)}</h3>
                    <ActionMenu items={actions(item)} ariaLabel={t("library.actionsFor", { name: templateDisplayName(t, item) })} />
                  </div>
                  <p className="studio-card-description">{templateDescription(t, item) || t("library.noDescription")}</p>
                  <div className="studio-card-badges">
                    <Badge variant={item.origin === "system" ? "neutral" : item.origin === "copy" ? "violet" : "info"}>{t(`origin.${item.origin}`)}</Badge>
                    {item.is_default && <Badge variant="success" dot>{t("library.default")}</Badge>}
                    {item.draft_revision && item.editable && <Badge variant="warning">{t("library.draft")}</Badge>}
                    {!item.published_revision && <Badge variant="warning">{t("library.unpublished")}</Badge>}
                    {item.status === "archived" && <Badge variant="neutral">{t("library.archivedBadge")}</Badge>}
                  </div>
                </div>
              </article>
            ))}
          </div>
        </section>
      ))}

      {createOpen && (
        <TemplateCreateModal
          open={createOpen}
          onClose={() => setCreateOpen(false)}
          types={scopeTypes}
          templates={templates ?? []}
          canUseDesigns={capabilities.manage_brand}
          onCreated={(created) => router.push(`/documents/templates/${created.id}`)}
        />
      )}
      {assignmentsOpen && <AssignmentsModal open={assignmentsOpen} onClose={() => { setAssignmentsOpen(false); load(); }} types={scopeTypes} templates={templates ?? []} />}
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
