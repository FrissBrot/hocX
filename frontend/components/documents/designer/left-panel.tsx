"use client";

// Linke Seitenleiste: Komponentenbibliothek, Dokumentstruktur (Ebenen), Datenquellen und
// wiederverwendbare Komponenten. Jedes Element lässt sich ziehen (Maus/Tastatur über dnd-kit)
// oder per Klick an der aktuellen Stelle einfügen.

import { useMemo, useState } from "react";
import { useDraggable } from "@dnd-kit/core";
import { useTranslations } from "next-intl";

import { isProtocolContent, ProtocolBlockList } from "@/components/documents/designer/block-appearance-panel";
import { modeAllows, useDesigner } from "@/components/documents/designer/designer-context";
import { bindingLabel, groupBindings } from "@/components/documents/studio-labels";
import { SearchInput } from "@/components/ui/search-input";
import { Tabs } from "@/components/ui/tabs";
import type { BindingInfo, LibraryEntry, ReusableComponent } from "@/lib/documents/api";
import { Area, areaNodes, inlineSummary, moveWithinParent, TemplateNode, TextContent, updateNode } from "@/lib/documents/layout";

export type InsertSource = { kind: "library"; key: string } | { kind: "binding"; path: string } | { kind: "component"; id: string };

type Props = { onInsert: (source: InsertSource) => void };

function DraggableItem({ id, data, children, onActivate, label, disabled }: { id: string; data: InsertSource; children: React.ReactNode; onActivate: () => void; label: string; disabled?: boolean }) {
  const { setNodeRef, listeners, attributes, isDragging } = useDraggable({ id, data, disabled });
  return (
    <div className={isDragging ? "studio-palette-item studio-palette-item-dragging" : "studio-palette-item"} ref={setNodeRef}>
      <button type="button" className="studio-palette-button" onClick={onActivate} disabled={disabled} aria-label={label}>
        {children}
      </button>
      {!disabled && (
        <span className="studio-palette-drag" {...listeners} {...attributes} role="button" aria-label={label}>
          ⠿
        </span>
      )}
    </div>
  );
}

function Palette({ onInsert }: Props) {
  const t = useTranslations("documentStudio");
  const { catalog, mode, capabilities, editable, documentType, activeArea } = useDesigner();
  const [query, setQuery] = useState("");
  const needsProtocolOk = catalog.document_types.find((item) => item.key === documentType)?.needs_protocol ?? false;
  const inMaster = activeArea.startsWith("master:");
  const entries = catalog.library.filter((entry) => modeAllows(mode, entry.mode) && (!entry.master_only || inMaster));
  const filtered = entries.filter((entry) => !query.trim() || t(`library.entry.${entry.key}`).toLowerCase().includes(query.trim().toLowerCase()));
  const groups = useMemo(() => {
    const result: Record<string, LibraryEntry[]> = {};
    for (const entry of filtered) (result[entry.group] ??= []).push(entry);
    return result;
  }, [filtered]);
  const restricted = (entry: LibraryEntry) => (entry.access === "finance" && !capabilities.finance_data) || (entry.access === "writer" && !capabilities.personal_data);
  return (
    <div className="studio-panel-scroll">
      <SearchInput value={query} onChange={setQuery} placeholder={t("palette.search")} />
      {Object.entries(groups).map(([group, items]) => (
        <section key={group} className="studio-palette-group" aria-label={t(`libraryGroup.${group}`)}>
          <h3 className="studio-palette-title">{t(`libraryGroup.${group}`)}</h3>
          <div className="studio-palette-list">
            {items.map((entry) => (
              <DraggableItem key={entry.key} id={`lib|${entry.key}`} data={{ kind: "library", key: entry.key }} onActivate={() => onInsert({ kind: "library", key: entry.key })} label={t("palette.insert", { name: t(`library.entry.${entry.key}`) })} disabled={!editable}>
                <span className="studio-palette-name">{t(`library.entry.${entry.key}`)}</span>
                <span className="studio-palette-help">
                  {t(`library.help.${entry.key}`)}
                  {entry.needs_protocol && !needsProtocolOk ? ` · ${t("fields.needsProtocol")}` : ""}
                  {restricted(entry) ? ` · ${t("fields.noPermission")}` : ""}
                </span>
              </DraggableItem>
            ))}
          </div>
        </section>
      ))}
      {filtered.length === 0 && <p className="muted">{t("palette.noResults")}</p>}
    </div>
  );
}

type Translator = ReturnType<typeof useTranslations>;

function nodeLabel(t: Translator, tPdf: Translator, node: TemplateNode): string {
  if (node.name) return node.name;
  const text = inlineSummary((node.title ?? node.content) as TextContent | undefined, (key) => (tPdf.has(key) ? tPdf(key) : key), (path) => bindingLabel(t, path));
  if (text) return text.length > 40 ? `${text.slice(0, 40)}…` : text;
  if (node.type === "data_block") return t(`component.${node.component as string}`);
  return t(`nodeType.${node.type}`);
}

function TreeItems({ nodes, depth }: { nodes: TemplateNode[]; depth: number }) {
  const t = useTranslations("documentStudio");
  const tPdf = useTranslations("documentPdf");
  const { selectedId, select, content, setContent, editable, diagnostics } = useDesigner();
  return (
    <ul className="studio-tree-list" role="group">
      {nodes.map((node) => {
        const issues = diagnostics.filter((item) => item.node_id === node.id);
        return (
          <li key={node.id} role="treeitem" aria-selected={selectedId === node.id} aria-level={depth + 1}>
            <div className={selectedId === node.id ? "studio-tree-row studio-tree-row-selected" : "studio-tree-row"}>
              <button type="button" className="studio-tree-name" onClick={() => select(node.id)}>
                <span className={node.enabled === false ? "studio-tree-label studio-tree-label-off" : "studio-tree-label"}>{nodeLabel(t, tPdf, node)}</span>
                {node.visible_if ? <span className="studio-tree-flag" title={t("structure.conditional")}>?</span> : null}
                {node.repeat ? <span className="studio-tree-flag" title={t("structure.repeated")}>↻</span> : null}
                {node.locked ? <span className="studio-tree-flag" title={t("structure.locked")}>🔒</span> : null}
                {issues.length > 0 ? <span className={issues.some((item) => item.severity === "error") ? "studio-tree-flag studio-tree-flag-error" : "studio-tree-flag studio-tree-flag-warning"} title={t("structure.hasIssues")}>!</span> : null}
              </button>
              {editable && (
                <span className="studio-tree-actions">
                  <button type="button" className="button-icon-soft button-icon-soft-sm" aria-label={node.enabled === false ? t("structure.show") : t("structure.hide")} onClick={() => setContent(updateNode(content, node.id, { enabled: node.enabled === false }))}>
                    {node.enabled === false ? "◌" : "●"}
                  </button>
                  <button type="button" className="button-icon-soft button-icon-soft-sm" aria-label={t("structure.moveUp")} onClick={() => setContent(moveWithinParent(content, node.id, -1))}>
                    ↑
                  </button>
                  <button type="button" className="button-icon-soft button-icon-soft-sm" aria-label={t("structure.moveDown")} onClick={() => setContent(moveWithinParent(content, node.id, 1))}>
                    ↓
                  </button>
                </span>
              )}
            </div>
            {node.children?.length ? <TreeItems nodes={node.children} depth={depth + 1} /> : null}
            {isProtocolContent(node) ? <ProtocolBlockList node={node} nested /> : null}
          </li>
        );
      })}
    </ul>
  );
}

function Structure() {
  const t = useTranslations("documentStudio");
  const { content, mode, setActiveArea, activeArea } = useDesigner();
  const areas: { area: Area; label: string }[] = [{ area: "body", label: t("canvas.body") }];
  if (content.title_page.enabled) areas.unshift({ area: "title_page", label: t("canvas.titlePage") });
  if (modeAllows(mode, "advanced")) {
    for (const master of content.masters) {
      const name = content.masters.length > 1 ? ` · ${master.name || master.id}` : "";
      if (master.header) areas.push({ area: `master:${master.id}:header`, label: `${t("canvas.header")}${name}` });
      if (master.footer) areas.push({ area: `master:${master.id}:footer`, label: `${t("canvas.footer")}${name}` });
      if (modeAllows(mode, "expert")) areas.push({ area: `master:${master.id}:background`, label: `${t("canvas.background")}${name}` });
    }
  }
  return (
    <div className="studio-panel-scroll" role="tree" aria-label={t("structure.title")}>
      {areas.map(({ area, label }) => (
        <section key={area} className="studio-tree-area">
          <button type="button" className={activeArea === area ? "studio-tree-area-title studio-tree-area-title-active" : "studio-tree-area-title"} onClick={() => setActiveArea(area)}>
            {label}
          </button>
          {areaNodes(content, area).length === 0 ? <p className="field-help">{t("structure.empty")}</p> : <TreeItems nodes={areaNodes(content, area)} depth={0} />}
        </section>
      ))}
    </div>
  );
}

function DataSources({ onInsert }: Props) {
  const t = useTranslations("documentStudio");
  const { catalog, capabilities, editable, documentType } = useDesigner();
  const needsProtocolOk = catalog.document_types.find((item) => item.key === documentType)?.needs_protocol ?? false;
  const groups = groupBindings(catalog.bindings.filter((binding) => binding.type !== "bool"));
  const restricted = (binding: BindingInfo) => (binding.access === "finance" && !capabilities.finance_data) || (binding.access === "writer" && !capabilities.personal_data);
  return (
    <div className="studio-panel-scroll">
      <p className="field-help">{t("data.help")}</p>
      {Object.entries(groups).map(([group, bindings]) => (
        <section key={group} className="studio-palette-group" aria-label={t(`bindingGroup.${group}`)}>
          <h3 className="studio-palette-title">{t(`bindingGroup.${group}`)}</h3>
          <div className="studio-palette-list">
            {bindings.map((binding) => (
              <DraggableItem
                key={binding.path}
                id={`bind|${binding.path}`}
                data={{ kind: "binding", path: binding.path }}
                onActivate={() => onInsert({ kind: "binding", path: binding.path })}
                label={t("palette.insert", { name: bindingLabel(t, binding.path) })}
                disabled={!editable || restricted(binding)}
              >
                <span className="studio-palette-name">{bindingLabel(t, binding.path)}</span>
                <span className="studio-palette-help">
                  {t(`bindingType.${binding.type}`)}
                  {binding.needs_protocol && !needsProtocolOk ? ` · ${t("fields.needsProtocol")}` : ""}
                  {restricted(binding) ? ` · ${t("fields.noPermission")}` : ""}
                </span>
              </DraggableItem>
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}

function Reusable({ onInsert }: Props) {
  const t = useTranslations("documentStudio");
  const { components, editable } = useDesigner();
  if (components.length === 0) return <p className="field-help studio-panel-scroll">{t("components.emptyHelp")}</p>;
  return (
    <div className="studio-panel-scroll">
      <div className="studio-palette-list">
        {components.map((component: ReusableComponent) => (
          <DraggableItem key={component.id} id={`comp|${component.id}`} data={{ kind: "component", id: component.id }} onActivate={() => onInsert({ kind: "component", id: component.id })} label={t("palette.insert", { name: component.name })} disabled={!editable}>
            <span className="studio-palette-name">{component.name}</span>
            <span className="studio-palette-help">{component.description ?? t(`nodeType.${component.node.type}`)}</span>
          </DraggableItem>
        ))}
      </div>
    </div>
  );
}

export function LeftPanel({ onInsert }: Props) {
  const t = useTranslations("documentStudio");
  const { mode } = useDesigner();
  const [tab, setTab] = useState("components");
  const tabs = [
    { id: "components", label: t("left.components"), content: <Palette onInsert={onInsert} /> },
    { id: "structure", label: t("left.structure"), content: <Structure /> },
    { id: "data", label: t("left.data"), content: <DataSources onInsert={onInsert} /> },
    ...(modeAllows(mode, "advanced") ? [{ id: "reusable", label: t("left.reusable"), content: <Reusable onInsert={onInsert} /> }] : []),
  ];
  return (
    <aside className="studio-left" aria-label={t("left.title")}>
      <Tabs tabs={tabs} activeId={tab} onChange={setTab} />
    </aside>
  );
}
