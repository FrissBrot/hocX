"use client";

// Gemeinsamer Zustand des Visual Designers: Layoutinhalt (mit Undo/Redo), Auswahl, Modus,
// Katalog, Rechte, Brand, Assets und Diagnosen. Alle drei Modi (Einfach, Erweitert, Experte)
// bearbeiten denselben Inhalt - ein Moduswechsel blendet nur Bedienelemente ein oder aus.

import { createContext, ReactNode, useCallback, useContext, useMemo } from "react";

import type { BrandView } from "@/components/documents/designer/brand-preview";
import type { Brand, CanvasData, Capabilities, Diagnostic, DocumentAsset, EditorMode, ReusableComponent, StudioCatalog } from "@/lib/documents/api";
import { Area, locate, TemplateContent, TemplateNode, updateNode } from "@/lib/documents/layout";

export type DesignerState = {
  content: TemplateContent;
  setContent: (next: TemplateContent, mergeKey?: string) => void;
  selectedId: string | null;
  select: (id: string | null) => void;
  mode: EditorMode;
  catalog: StudioCatalog;
  capabilities: Capabilities;
  brand: BrandView;
  brands: Brand[];
  assets: DocumentAsset[];
  setAssets: (assets: DocumentAsset[]) => void;
  components: ReusableComponent[];
  setComponents: (components: ReusableComponent[]) => void;
  diagnostics: Diagnostic[];
  documentType: string;
  editable: boolean;
  activeArea: Area;
  setActiveArea: (area: Area) => void;
  // Datenquelle der Vorschau und der Arbeitsfläche (Beispielinhalte oder echtes Protokoll)
  dataMode: "sample" | "data";
  setDataMode: (mode: "sample" | "data") => void;
  protocolId: string | null;
  setProtocolId: (id: string | null) => void;
  // Aufgelöste Werte für die Arbeitsfläche (null, solange nicht geladen)
  canvasData: CanvasData | null;
};

const DesignerContext = createContext<DesignerState | null>(null);

export function DesignerProvider({ value, children }: { value: DesignerState; children: ReactNode }) {
  return <DesignerContext.Provider value={value}>{children}</DesignerContext.Provider>;
}

export function useDesigner(): DesignerState {
  const value = useContext(DesignerContext);
  if (!value) throw new Error("useDesigner ausserhalb des Designers"); // i18n-ok: Programmierfehler (Hook ohne Provider), kein UI-Text
  return value;
}

/** Ausgewählter Knoten und eine Funktion, ihn zu ändern (eine Undo-Stufe je Feld). */
export function useSelectedNode() {
  const { content, setContent, selectedId } = useDesigner();
  const location = selectedId ? locate(content, selectedId) : null;
  const change = useCallback(
    (patch: Partial<TemplateNode> | ((node: TemplateNode) => TemplateNode), mergeKey?: string) => {
      if (!selectedId) return;
      setContent(updateNode(content, selectedId, patch), mergeKey ? `${selectedId}:${mergeKey}` : undefined);
    },
    [content, selectedId, setContent]
  );
  return useMemo(() => ({ node: location?.node ?? null, location, change }), [location, change]);
}

export function modeAllows(current: EditorMode, required: EditorMode): boolean {
  const order: EditorMode[] = ["simple", "advanced", "expert"];
  return order.indexOf(current) >= order.indexOf(required);
}

export function diagnosticsFor(diagnostics: Diagnostic[], nodeId: string): Diagnostic[] {
  return diagnostics.filter((item) => item.node_id === nodeId);
}
