// Katalog der Gestaltung auf Abruf: mitgelieferte Designs (Alpin, Kreide …) und Systemvorlagen
// liegen zentral und werden erst beim Übernehmen als eigene Vorlage in den Verein kopiert. Ein
// Design zeigt sein eigenes CD (Mockup mit Logo und Bildern) und bringt es beim Übernehmen als
// verknüpftes Erscheinungsbild mit. Reine Hilfsfunktionen: sie bekommen ``t`` (Namespace
// documentStudio) übergeben.

import { templateDescription, templateDisplayName } from "@/components/documents/studio-labels";
import { DesignExample, DocumentTemplateDetail, DocumentTemplateInfo, DocumentTypeInfo, studioApi } from "@/lib/documents/api";

type TFunc = (key: string, values?: Record<string, string | number>) => string;

// Kategorie der Sitzungsdokumente (Protokoll, Einladung, Traktandenliste)
export const SESSION_CATEGORY = "protocols";

export type CatalogItem = {
  key: string;
  kind: "design" | "system";
  documentType: string;
  name: string;
  description: string;
  thumbnail: string;
  // Systemvorlage (nur kind="system")
  template: DocumentTemplateInfo | null;
  // Schon als eigene Vorlage übernommen
  adopted: boolean;
};

/** Eigene und übernommene Vorlagen des Vereins (ohne den Katalog selbst). */
export function ownTemplates(templates: DocumentTemplateInfo[]): DocumentTemplateInfo[] {
  return templates.filter((item) => item.origin !== "system");
}

/** Alle Katalog-Einträge; ``brandVersion`` aktualisiert die Vorschau der Systemvorlagen, die mit
 * dem Erscheinungsbild des Vereins gerendert wird. Designs zeigen ihr mitgeliefertes Vorschaubild. */
export function catalogItems(t: TFunc, templates: DocumentTemplateInfo[], designs: DesignExample[], brandVersion: string): CatalogItem[] {
  const active = templates.filter((item) => item.status === "active" && item.origin !== "system");
  const fromDesigns: CatalogItem[] = designs.map((design) => ({
    key: `design:${design.key}`,
    kind: "design",
    documentType: design.document_type,
    name: t("catalog.designName", { type: t(`docType.${design.document_type}`), design: t(`examples.items.${design.key}.name`) }),
    description: t(`examples.items.${design.key}.description`),
    thumbnail: studioApi.exampleThumbnailUrl(design.key),
    template: null,
    adopted: active.some((item) => item.catalog_key === design.key),
  }));
  const fromSystem: CatalogItem[] = templates
    .filter((item) => item.origin === "system" && item.status === "active" && item.published_revision)
    .map((item) => ({
      key: `system:${item.system_key ?? item.id}`,
      kind: "system",
      documentType: item.document_type,
      name: templateDisplayName(t, item),
      description: templateDescription(t, item),
      thumbnail: studioApi.thumbnailUrl(item.id, `${item.published_revision?.id ?? item.updated_at}:${brandVersion}`),
      template: item,
      adopted: active.some((own) => own.source_system_key === item.system_key),
    }));
  return [...fromDesigns, ...fromSystem];
}

/** Herkunft einer eigenen Vorlage: «Eigene» oder «Aus Katalog · Alpin». */
export function originLabel(t: TFunc, template: DocumentTemplateInfo): { label: string; fromCatalog: boolean } {
  if (template.catalog_key) return { label: t("catalog.fromCatalog", { name: t(`examples.items.${template.catalog_key}.name`) }), fromCatalog: true };
  if (template.origin === "copy" && template.source_system_key) return { label: t("catalog.fromCatalog", { name: t(`system.${template.source_system_key}.name`) }), fromCatalog: true };
  return { label: t("origin.tenant"), fromCatalog: false };
}

/** Katalog-Eintrag als eigene Vorlage übernehmen; ein Design mit ``withBrand`` samt seinem CD. */
export function adoptCatalogItem(item: CatalogItem, name: string, withBrand = false): Promise<DocumentTemplateDetail> {
  if (item.kind === "design") return studioApi.importExample(item.key.slice("design:".length), name, withBrand);
  return studioApi.duplicateTemplate(item.template!.id, name);
}

/** Dokumenttypen nach Kategorie gruppiert, in der Reihenfolge des Katalogs. */
export function typesByCategory(types: DocumentTypeInfo[], categories: string[]): { category: string; types: DocumentTypeInfo[] }[] {
  return categories
    .map((category) => ({ category, types: types.filter((type) => type.category === category) }))
    .filter((group) => group.types.length > 0);
}
