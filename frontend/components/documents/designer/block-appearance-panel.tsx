"use client";

// Darstellung einzelner Bausteine des Protokollinhalts. Gehört die Gestaltung allein einer
// Sitzungsvorlage, listet der Designer deren Traktanden und Bausteine (Struktur links und
// Eigenschaften des Knotens «Protokollinhalt»); ein Baustein erbt die Darstellung des Knotens
// bzw. des Brand-Profils und kann sie je Elementart übersteuern (DataBlockNode.block_appearance,
// Schlüssel = Herkunft in der Sitzungsvorlage, backend/app/documents/appearance.py).

import { useTranslations } from "next-intl";

import { AppearanceEditor } from "@/components/documents/appearance-editor";
import { useDesigner } from "@/components/documents/designer/designer-context";
import type { ProtocolStructureBlock } from "@/lib/documents/api";
import { brandVariant } from "@/lib/documents/appearance";
import { AppearanceOverrides, locate, TemplateNode, updateNode } from "@/lib/documents/layout";

type BlockOverrides = Record<string, AppearanceOverrides>;

export function isProtocolContent(node: TemplateNode): boolean {
  return node.type === "data_block" && node.component === "protocol_element";
}

function overridesOf(node: TemplateNode): BlockOverrides {
  return (node.block_appearance as BlockOverrides | undefined) ?? {};
}

/** Traktanden und Bausteine der Sitzungsvorlage; ein Klick wählt den Baustein aus. */
export function ProtocolBlockList({ node, nested = false }: { node: TemplateNode; nested?: boolean }) {
  const t = useTranslations("documentStudio");
  const tTypes = useTranslations("templates");
  const { protocolStructure, selectedBlock, selectBlock } = useDesigner();
  if (!protocolStructure) return null;
  if (!protocolStructure.owned) return <p className="field-help studio-tree-hint">{t("blockAppearance.notOwned")}</p>;
  const overrides = overridesOf(node);
  const elements = protocolStructure.elements.filter((element) => element.blocks.length > 0);
  if (elements.length === 0) return <p className="field-help studio-tree-hint">{t("blockAppearance.empty")}</p>;
  return (
    <ul className={nested ? "studio-tree-list" : "studio-tree-list studio-block-list"} role="group" aria-label={t("blockAppearance.listLabel")}>
      {elements.map((element) => (
        <li key={element.id} className="studio-tree-group">
          <span className="studio-tree-group-title">{element.title}</span>
          <ul className="studio-tree-list" role="group">
            {element.blocks.map((block) => {
              const selected = selectedBlock?.nodeId === node.id && selectedBlock.key === block.key;
              return (
                <li key={block.key} role="treeitem" aria-selected={selected}>
                  <div className={selected ? "studio-tree-row studio-tree-row-selected" : "studio-tree-row"}>
                    <button type="button" className="studio-tree-name" onClick={() => selectBlock({ nodeId: node.id, key: block.key })}>
                      <span className="studio-tree-label">{blockLabel(tTypes, block)}</span>
                      {overrides[block.key] ? (
                        <span className="studio-tree-flag" title={t("blockAppearance.overridden")}>
                          ◆
                        </span>
                      ) : null}
                    </button>
                  </div>
                </li>
              );
            })}
          </ul>
        </li>
      ))}
    </ul>
  );
}

// Ohne eigenen Titel: Name des Bausteintyps (templates.elementTypes, wie im Vorlagen-Editor)
function blockLabel(tTypes: ReturnType<typeof useTranslations>, block: ProtocolStructureBlock): string {
  const key = `elementTypes.${block.element_type_id}.label`;
  return block.title || (tTypes.has(key) ? tTypes(key) : block.element_type);
}

/** Rechte Seite bei ausgewähltem Baustein. */
export function BlockAppearancePanel() {
  const t = useTranslations("documentStudio");
  const tTypes = useTranslations("templates");
  const { content, setContent, selectedBlock, select, protocolStructure, catalog, brand, editable } = useDesigner();
  if (!selectedBlock) return null;
  const node = locate(content, selectedBlock.nodeId)?.node;
  if (!node) return null;
  const element = protocolStructure?.elements.find((item) => item.blocks.some((block) => block.key === selectedBlock.key));
  const block = element?.blocks.find((item) => item.key === selectedBlock.key);
  const overrides = overridesOf(node);
  const own = overrides[selectedBlock.key];
  const nodeAppearance = node.appearance as AppearanceOverrides | undefined;

  function setOwn(next: AppearanceOverrides | null) {
    if (!node || !selectedBlock) return;
    const all = { ...overrides };
    if (next && Object.keys(next).length > 0) all[selectedBlock.key] = next;
    else delete all[selectedBlock.key];
    setContent(updateNode(content, node.id, { block_appearance: all }), `${node.id}:block:${selectedBlock.key}`);
  }

  return (
    <div className="studio-properties" aria-label={t("blockAppearance.title")}>
      <div className="studio-prop-header">
        <div>
          <span className="studio-prop-type">{t("blockAppearance.title")}</span>
          {block && <h3 className="studio-block-title">{blockLabel(tTypes, block)}</h3>}
          {element && <p className="field-help">{t("blockAppearance.inElement", { element: element.title })}</p>}
        </div>
      </div>
      {block && block.appearance_kinds.length > 0 && catalog.appearance ? (
        <>
          <p className="field-help">{t("blockAppearance.help")}</p>
          <AppearanceEditor
            catalog={catalog.appearance}
            kinds={block.appearance_kinds}
            value={own}
            inherited={(kind) => nodeAppearance?.[kind]?.variant ?? brandVariant(brand.tokens, catalog.appearance, kind)}
            inheritLabel={(value) => t("blockAppearance.inherit", { value })}
            onChange={setOwn}
            disabled={!editable}
          />
        </>
      ) : (
        // Ohne Optionen bzw. Baustein, den es in der Sitzungsvorlage nicht mehr gibt
        <p className="field-help">{block ? t("blockAppearance.noOptions") : t("blockAppearance.missing")}</p>
      )}
      <div className="studio-block-actions">
        <button type="button" className="button-ghost" onClick={() => select(node.id)}>
          {t("blockAppearance.back")}
        </button>
        {own && editable && (
          <button type="button" className="button-secondary" onClick={() => setOwn(null)}>
            {t("blockAppearance.reset")}
          </button>
        )}
      </div>
    </div>
  );
}
