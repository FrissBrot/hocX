"use client";

// Visual Designer des Document Studio. Links Bibliothek/Struktur/Daten, Mitte Arbeitsfläche
// (angenähert) und/oder Typst-Vorschau (verbindlich), rechts Eigenschaften. Speichern per
// Autosave in den Entwurf (optimistische Sperre gegen parallele Bearbeitung), Undo/Redo,
// Tastaturbedienung und Drag-and-drop. Veröffentlichen prüft die Vorlage serverseitig.

import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { DndContext, DragEndEvent, KeyboardSensor, PointerSensor, useSensor, useSensors } from "@dnd-kit/core";
import { useTranslations } from "next-intl";
import type { Route } from "next";
import { useRouter } from "next/navigation";

import { brandView, mm } from "@/components/documents/designer/brand-preview";
import { Canvas, parseDropId } from "@/components/documents/designer/canvas";
import { useCanvasData } from "@/components/documents/designer/canvas-data";
import { DesignerProvider, DesignerState } from "@/components/documents/designer/designer-context";
import { DocumentPanel } from "@/components/documents/designer/document-panel";
import { InsertSource, LeftPanel } from "@/components/documents/designer/left-panel";
import { PreviewPanel } from "@/components/documents/designer/preview-panel";
import { PropertiesPanel } from "@/components/documents/designer/properties-panel";
import { SaveState, Toolbar, ViewMode } from "@/components/documents/designer/toolbar";
import { templateDisplayName } from "@/components/documents/studio-labels";
import { StatusBanner } from "@/components/ui/status-banner";
import { useConfirm } from "@/contexts/confirm-context";
import { useToast } from "@/contexts/toast-context";
import { ApiError } from "@/lib/api/client";
import { apiErrorMessage, Brand, Capabilities, Diagnostic, DocumentAsset, DocumentTemplateDetail, EditorMode, ReusableComponent, studioApi, StudioCatalog } from "@/lib/documents/api";
import { useHistory } from "@/lib/documents/history";
import { Area, BrandTokens, duplicateNode, insertNode, locate, moveNode, moveWithinParent, pageDimensions, removeNode, TemplateContent, TemplateNode, withFreshIds } from "@/lib/documents/layout";

const AUTOSAVE_MS = 1200;
// Platz links (Bereichsbeschriftungen) und rechts neben der Seite auf der Arbeitsfläche, in px
const CANVAS_GUTTER_PX = 84 + 32;
// Ab dieser Breite der Mitte startet der Designer geteilt (Arbeitsfläche + Vorschau)
const SPLIT_MIN_CENTER_PX = 900;
const SPLIT_CANVAS_SHARE = 3 / 5;
const MODE_STORAGE_KEY = "hocx.documentStudio.mode";

type Loaded = { template: DocumentTemplateDetail; catalog: StudioCatalog; capabilities: Capabilities; brands: Brand[]; assets: DocumentAsset[]; components: ReusableComponent[] };

/** ``sessionTemplateId``: eingebettet im Vorlagen-Editor einer Sitzungsvorlage; die Vorschau zeigt
 * deren Traktanden mit den Inhalten der letzten Sitzung. */
export function TemplateDesigner({ templateId, sessionTemplateId = null }: { templateId: string; sessionTemplateId?: string | null }) {
  const t = useTranslations("documentStudio");
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    Promise.all([studioApi.getTemplate(templateId), studioApi.catalog(), studioApi.capabilities(), studioApi.brands(), studioApi.assets(), studioApi.components()])
      .then(([template, catalog, capabilities, brands, assets, components]) => setLoaded({ template, catalog, capabilities, brands: brands ?? [], assets: assets ?? [], components: components ?? [] }))
      .catch((reason) => setError(apiErrorMessage(reason, t("designer.loadFailed"))));
    // t/toast sind während der Lebensdauer der Komponente unveränderlich
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [templateId]);
  if (error) return <StatusBanner tone="error" message={error} />;
  if (!loaded) return <p className="muted">{t("common.loading")}</p>;
  return <DesignerWorkspace key={loaded.template.working_revision_id ?? loaded.template.id} initial={loaded} sessionTemplateId={sessionTemplateId} />;
}

function readMode(): EditorMode {
  try {
    const value = window.localStorage.getItem(MODE_STORAGE_KEY);
    return value === "advanced" || value === "expert" ? value : "simple";
  } catch {
    return "simple";
  }
}

function DesignerWorkspace({ initial, sessionTemplateId }: { initial: Loaded; sessionTemplateId: string | null }) {
  const t = useTranslations("documentStudio");
  const router = useRouter();
  const toast = useToast();
  const confirm = useConfirm();
  const [template, setTemplate] = useState(initial.template);
  const history = useHistory<TemplateContent>(initial.template.content);
  const content = history.value;
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [mode, setModeState] = useState<EditorMode>("simple");
  const [view, setView] = useState<ViewMode>("split");
  const [zoom, setZoom] = useState(0.8);
  const centerRef = useRef<HTMLElement>(null);
  const [activeArea, setActiveArea] = useState<Area>("body");
  const [assets, setAssets] = useState(initial.assets);
  const [components, setComponents] = useState(initial.components);
  const [saveDiagnostics, setSaveDiagnostics] = useState<Diagnostic[]>(initial.template.diagnostics);
  const [previewDiagnostics, setPreviewDiagnostics] = useState<Diagnostic[]>([]);
  // Im Vorlagen-Editor gleich mit echten Daten (Traktanden der Vorlage, Inhalte der letzten Sitzung)
  const [dataMode, setDataMode] = useState<"sample" | "data">(sessionTemplateId ? "data" : "sample");
  const [protocolId, setProtocolId] = useState<string | null>(null);
  const [saveState, setSaveState] = useState<SaveState>("saved");
  const initialBrandMode = (initial.template.draft_revision ?? initial.template.published_revision)?.brand_mode ?? "follow";
  const [brandMode, setBrandMode] = useState<"follow" | "pinned">(initialBrandMode);
  const [name, setName] = useState(templateDisplayName(t, initial.template));
  // Speicherstand in Refs: Autosave-Timer und laufende Anfragen lesen immer den aktuellen
  // Stand statt der Closure des Renders, in dem sie gestartet wurden (sonst veraltete
  // Sperrversion -> Schein-Konflikt, bzw. «gespeichert» trotz neuerer Änderungen).
  const lockRef = useRef<number | null>(initial.template.draft_revision?.lock_version ?? null);
  const savedContent = useRef<TemplateContent>(initial.template.content);
  const savedBrandMode = useRef<"follow" | "pinned">(initialBrandMode);
  const contentRef = useRef<TemplateContent>(content);
  const brandModeRef = useRef(brandMode);
  contentRef.current = content;
  brandModeRef.current = brandMode;
  // Laufender Speichervorgang; weitere Aufrufe währenddessen werden danach nachgeholt
  const inFlight = useRef<Promise<void> | null>(null);
  const saveAgain = useRef(false);
  const isDirty = () => contentRef.current !== savedContent.current || brandModeRef.current !== savedBrandMode.current;
  const editable = template.editable;

  useEffect(() => setModeState(readMode()), []);
  const setMode = (next: EditorMode) => {
    setModeState(next);
    try {
      window.localStorage.setItem(MODE_STORAGE_KEY, next);
    } catch {
      // Speicher nicht verfügbar: Modus gilt nur für diese Sitzung
    }
  };

  const brand = useMemo(() => {
    const selected = initial.brands.find((item) => item.id === template.brand_id) ?? initial.brands.find((item) => item.is_default) ?? initial.brands[0];
    return brandView((selected?.tokens ?? null) as BrandTokens, content.settings.brand_overrides);
  }, [initial.brands, template.brand_id, content.settings.brand_overrides]);

  // Zoom an die verfügbare Breite anpassen (beim Öffnen und bei Ansicht/Seitenformat-Wechsel)
  const master = content.masters.find((item) => item.id === content.settings.default_master) ?? content.masters[0];
  const [pageWidthMm] = pageDimensions(content.page, master?.orientation);
  useLayoutEffect(() => {
    const width = centerRef.current?.clientWidth ?? 0;
    if (width && width < SPLIT_MIN_CENTER_PX) setView((current) => (current === "split" ? "design" : current));
  }, []);
  useLayoutEffect(() => {
    const width = centerRef.current?.clientWidth ?? 0;
    if (!width || view === "preview") return;
    const available = width * (view === "split" ? SPLIT_CANVAS_SHARE : 1) - CANVAS_GUTTER_PX;
    const fitted = Math.round((available / mm(pageWidthMm, 1)) * 20) / 20;
    setZoom(Math.min(1.2, Math.max(0.4, fitted)));
  }, [view, pageWidthMm]);

  // ── Speichern ───────────────────────────────────────────────────────────
  const runSave = useCallback(
    async (force: boolean) => {
      let overwrite = force;
      do {
        saveAgain.current = false;
        const snapshot = contentRef.current;
        const snapshotMode = brandModeRef.current;
        setSaveState("saving");
        try {
          const result = await studioApi.saveDraft(template.id, { content: snapshot, lock_version: overwrite ? null : lockRef.current, brand_mode: snapshotMode });
          overwrite = false;
          savedContent.current = snapshot;
          savedBrandMode.current = snapshotMode;
          lockRef.current = result.revision.lock_version;
          setSaveDiagnostics(result.diagnostics);
          setTemplate((current) => ({ ...current, draft_revision: result.revision }));
          setSaveState(isDirty() ? "dirty" : "saved");
        } catch (reason) {
          saveAgain.current = false;
          if (reason instanceof ApiError && reason.status === 409) {
            setSaveState("conflict");
            return;
          }
          const detail = reason instanceof ApiError && reason.detail && typeof reason.detail === "object" ? (reason.detail as { node_id?: string; code?: string }) : null;
          if (detail?.node_id) setSelectedId(detail.node_id);
          setSaveState("error");
          toast(apiErrorMessage(reason, t("designer.saveFailed")), "error");
          return;
        }
        // Während der Anfrage angeforderte Speicherung (Timer/Strg+S) jetzt nachholen
      } while (saveAgain.current && isDirty());
    },
    // isDirty liest nur Refs
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [template.id, toast, t]
  );

  const save = useCallback(
    (force = false): Promise<void> => {
      if (!editable) return Promise.resolve();
      if (inFlight.current) {
        // Nie zwei Anfragen parallel: die zweite käme mit veralteter Sperrversion an
        saveAgain.current = true;
        return inFlight.current;
      }
      const running = runSave(force).finally(() => {
        inFlight.current = null;
      });
      inFlight.current = running;
      return running;
    },
    [editable, runSave]
  );

  useEffect(() => {
    if (!editable || !isDirty() || saveState === "conflict") return;
    if (!inFlight.current) setSaveState("dirty");
    const timer = window.setTimeout(() => void save(), AUTOSAVE_MS);
    return () => window.clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [content, brandMode]);

  useEffect(() => {
    const warn = (event: BeforeUnloadEvent) => {
      if (saveState === "dirty" || saveState === "saving" || saveState === "conflict") {
        event.preventDefault();
        event.returnValue = "";
      }
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [saveState]);

  // Verlassen mit ungespeicherten Änderungen (STUDIO-016): beforeunload deckt nur Neuladen und
  // Schliessen ab, nicht die client-seitige Navigation der App. Interne Links und «Zurück» speichern
  // zuerst; gelingt das nicht, fragt der Designer nach.
  const leave = useCallback(
    async (href: string) => {
      if (editable && (inFlight.current || isDirty())) {
        await save();
        if (isDirty() && !(await confirm({ message: t("designer.leaveUnsaved"), tone: "danger", confirmLabel: t("designer.leaveAnyway") }))) return;
      }
      router.push(href as Route);
    },
    // isDirty liest nur Refs
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [editable, save, confirm, router, t]
  );

  useEffect(() => {
    const onClick = (event: MouseEvent) => {
      if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
      const anchor = (event.target as Element | null)?.closest?.("a[href]") as HTMLAnchorElement | null;
      if (!anchor || anchor.target === "_blank" || anchor.hasAttribute("download")) return;
      const url = new URL(anchor.href, window.location.href);
      if (url.origin !== window.location.origin || (url.pathname === window.location.pathname && url.search === window.location.search)) return;
      if (!editable || (!inFlight.current && !isDirty())) return;
      event.preventDefault();
      event.stopPropagation();
      void leave(url.pathname + url.search + url.hash);
    };
    document.addEventListener("click", onClick, true);
    return () => document.removeEventListener("click", onClick, true);
    // isDirty liest nur Refs
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [editable, leave]);

  async function rename(next: string) {
    setName(next);
    if (!next.trim()) return;
    try {
      await studioApi.updateTemplate(template.id, { name: next.trim() });
    } catch (reason) {
      toast(apiErrorMessage(reason, t("designer.saveFailed")), "error");
    }
  }

  async function changeBrand(brandId: string | null) {
    try {
      const updated = brandId ? await studioApi.updateTemplate(template.id, { brand_id: brandId }) : await studioApi.updateTemplate(template.id, { clear_brand: true });
      setTemplate((current) => ({ ...current, brand_id: updated.brand_id }));
    } catch (reason) {
      toast(apiErrorMessage(reason, t("designer.saveFailed")), "error");
    }
  }

  async function publish() {
    // Veröffentlicht wird der serverseitige Entwurf: vorher alle Änderungen speichern
    if (inFlight.current || isDirty()) await save();
    if (isDirty()) return;
    const errors = [...saveDiagnostics].filter((item) => item.severity === "error");
    if (errors.length) {
      toast(t("designer.publishBlocked", { count: errors.length }), "error");
      if (errors[0].node_id) setSelectedId(errors[0].node_id);
      return;
    }
    if (!(await confirm({ message: t("designer.publishConfirm"), confirmLabel: t("toolbar.publish") }))) return;
    try {
      const published = await studioApi.publish(template.id);
      setTemplate(published);
      lockRef.current = null;
      toast(t("designer.published"), "success");
    } catch (reason) {
      const detail = reason instanceof ApiError && reason.detail && typeof reason.detail === "object" ? (reason.detail as { diagnostics?: Diagnostic[] }) : null;
      if (detail?.diagnostics) {
        setSaveDiagnostics(detail.diagnostics);
        const first = detail.diagnostics.find((item) => item.node_id);
        if (first?.node_id) setSelectedId(first.node_id);
      }
      toast(apiErrorMessage(reason, t("designer.publishFailed")), "error");
    }
  }

  function resetBrandMode(reloaded: DocumentTemplateDetail) {
    const next = (reloaded.draft_revision ?? reloaded.published_revision)?.brand_mode ?? "follow";
    savedBrandMode.current = next;
    brandModeRef.current = next;
    setBrandMode(next);
  }

  async function discard() {
    if (!(await confirm({ message: t("designer.discardConfirm"), tone: "danger", confirmLabel: t("toolbar.discard") }))) return;
    try {
      const reloaded = await studioApi.discardDraft(template.id);
      setTemplate(reloaded);
      history.reset(reloaded.content);
      savedContent.current = reloaded.content;
      resetBrandMode(reloaded);
      lockRef.current = null;
      setSaveState("saved");
    } catch (reason) {
      toast(apiErrorMessage(reason, t("common.actionFailed")), "error");
    }
  }

  async function reloadAfterConflict() {
    const reloaded = await studioApi.getTemplate(template.id);
    setTemplate(reloaded);
    history.reset(reloaded.content);
    savedContent.current = reloaded.content;
    resetBrandMode(reloaded);
    lockRef.current = reloaded.draft_revision?.lock_version ?? null;
    setSaveState("saved");
  }

  async function duplicateSystem() {
    try {
      const copy = await studioApi.duplicateTemplate(template.id, t("library.copyName", { name }));
      router.push(`/documents/templates/${copy.id}`);
    } catch (reason) {
      toast(apiErrorMessage(reason, t("common.actionFailed")), "error");
    }
  }

  // ── Einfügen und Verschieben ────────────────────────────────────────────
  const buildNode = useCallback(
    (source: InsertSource): TemplateNode | null => {
      if (source.kind === "library") {
        const entry = initial.catalog.library.find((item) => item.key === source.key);
        return entry ? withFreshIds(entry.node as TemplateNode) : null;
      }
      if (source.kind === "component") return withFreshIds({ id: "", type: "component_ref", component_id: source.id });
      const binding = initial.catalog.bindings.find((item) => item.path === source.path);
      if (!binding) return null;
      if (binding.type === "image") return withFreshIds({ id: "", type: "image", source: { kind: "binding", path: binding.path }, style: { width: "40mm" } });
      if (binding.type === "list") {
        return withFreshIds({
          id: "",
          type: "table",
          source: binding.path,
          columns: binding.item_fields.slice(0, 4).map((field) => ({ id: "", header: { default: [{ t: "text", v: t(`bindingField.${field.key}`) }] }, cell: { default: [{ t: "bind", path: `item.${field.key}` }] }, width: "auto", align: "left" })),
        });
      }
      return withFreshIds({ id: "", type: "text", content: { default: [{ t: "bind", path: binding.path, ...(binding.type === "date" ? { format: { date: "long" } } : {}) }] } });
    },
    [initial.catalog, t]
  );

  const insertAtSelection = useCallback(
    (source: InsertSource) => {
      const node = buildNode(source);
      if (!node || !editable) return;
      const location = selectedId ? locate(content, selectedId) : null;
      let next: TemplateContent;
      if (location && initial.catalog.node_types[location.node.type]?.container && location.node.type !== "row") {
        next = insertNode(content, location.area, location.node.id, location.node.children?.length ?? 0, node);
      } else if (location) {
        next = insertNode(content, location.area, location.parentId, location.index + 1, node);
      } else {
        const nodes = activeArea === "body" ? content.body : activeArea === "title_page" ? content.title_page.children : [];
        next = insertNode(content, activeArea, null, nodes.length, node);
      }
      history.set(next);
      setSelectedId(node.id);
    },
    [buildNode, editable, selectedId, content, initial.catalog.node_types, activeArea, history]
  );

  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 4 } }), useSensor(KeyboardSensor));
  const onDragEnd = (event: DragEndEvent) => {
    if (!editable || !event.over) return;
    const target = parseDropId(String(event.over.id));
    if (!target) return;
    const data = event.active.data.current as InsertSource | { kind: "node"; id: string } | undefined;
    if (!data) return;
    if (data.kind === "node") {
      history.set(moveNode(content, data.id, target.area, target.parentId, target.index));
      return;
    }
    const node = buildNode(data);
    if (!node) return;
    history.set(insertNode(content, target.area, target.parentId, target.index, node));
    setSelectedId(node.id);
  };

  // ── Tastatur ────────────────────────────────────────────────────────────
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      const typing = !!target && (target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.tagName === "SELECT" || target.isContentEditable);
      const meta = event.metaKey || event.ctrlKey;
      if (meta && event.key.toLowerCase() === "s") {
        event.preventDefault();
        void save();
        return;
      }
      if (typing) return;
      // Offener Dialog (Revisionen, Zuweisungen, Rückfrage): Tasten gehören dem Dialog
      if (document.querySelector('[aria-modal="true"]')) return;
      // Löschen/Duplizieren/Verschieben nur mit Fokus auf Arbeitsfläche oder Struktur, nicht z. B.
      // auf einem Knopf der Werkzeugleiste oder im Eigenschaftenbereich
      const onElements = !(target instanceof HTMLElement) || target === document.body || !!target.closest('.studio-center, [role="tree"]');
      if (meta && event.key.toLowerCase() === "z") {
        event.preventDefault();
        if (event.shiftKey) history.redo();
        else history.undo();
      } else if (meta && event.key.toLowerCase() === "y") {
        event.preventDefault();
        history.redo();
      } else if (!editable || !onElements) {
        return;
      } else if ((event.key === "Delete" || event.key === "Backspace") && selectedId) {
        event.preventDefault();
        history.set(removeNode(content, selectedId));
        setSelectedId(null);
      } else if (meta && event.key.toLowerCase() === "d" && selectedId) {
        event.preventDefault();
        const result = duplicateNode(content, selectedId);
        history.set(result.content);
        if (result.newId) setSelectedId(result.newId);
      } else if (event.altKey && (event.key === "ArrowUp" || event.key === "ArrowDown") && selectedId) {
        event.preventDefault();
        history.set(moveWithinParent(content, selectedId, event.key === "ArrowUp" ? -1 : 1));
      } else if (event.key === "Escape") {
        setSelectedId(null);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [save, history, editable, selectedId, content]);

  const canvasData = useCanvasData({
    content,
    documentType: template.document_type,
    dataMode,
    protocolId,
    brandId: template.brand_id,
    needsProtocol: !sessionTemplateId && (initial.catalog.document_types.find((item) => item.key === template.document_type)?.needs_protocol ?? false),
    sessionTemplateId,
  });

  const diagnostics = useMemo(() => {
    const seen = new Set<string>();
    // Ohne Vorschau (nur Arbeitsfläche) kommen die Hinweise aus der Arbeitsflächen-Antwort
    const canvasDiagnostics = view === "design" ? (canvasData?.diagnostics ?? []) : [];
    return [...saveDiagnostics, ...previewDiagnostics, ...canvasDiagnostics].filter((item) => {
      const key = `${item.node_id}|${item.code}|${item.detail}`;
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    });
  }, [saveDiagnostics, previewDiagnostics, canvasData, view]);

  const state: DesignerState = {
    content,
    setContent: history.set,
    selectedId,
    select: setSelectedId,
    mode,
    catalog: initial.catalog,
    capabilities: initial.capabilities,
    brand,
    brands: initial.brands,
    assets,
    setAssets,
    components,
    setComponents,
    diagnostics,
    documentType: template.document_type,
    editable,
    activeArea,
    setActiveArea,
    dataMode,
    setDataMode,
    protocolId,
    setProtocolId,
    canvasData,
    sessionTemplateId,
  };

  const status = template.draft_revision ? "draft" : template.published_revision ? "published" : "unpublished";
  const errorCount = diagnostics.filter((item) => item.severity === "error").length;

  return (
    <DesignerProvider value={state}>
      <DndContext sensors={sensors} onDragEnd={onDragEnd}>
        <div className="studio-designer">
          <Toolbar
            name={name}
            onRename={(next) => void rename(next)}
            editable={editable}
            saveState={saveState}
            onSave={() => void save()}
            canUndo={history.canUndo}
            canRedo={history.canRedo}
            onUndo={history.undo}
            onRedo={history.redo}
            mode={mode}
            onModeChange={setMode}
            view={view}
            onViewChange={setView}
            page={content.page}
            onPageSize={(size) => history.set({ ...content, page: { ...content.page, size } })}
            onOrientation={(orientation) => history.set({ ...content, page: { ...content.page, orientation } })}
            zoom={zoom}
            onZoom={setZoom}
            status={status}
            canPublish={(initial.capabilities.publish_templates || (initial.capabilities.edit_templates && !!template.session_template_id)) && editable}
            onPublish={() => void publish()}
            onDiscard={editable && template.draft_revision && template.published_revision ? () => void discard() : null}
            onBack={sessionTemplateId ? undefined : () => void leave("/documents")}
            errorCount={errorCount}
          />
          {!editable && (
            <div className="studio-readonly">
              <StatusBanner tone="neutral" message={template.origin === "system" ? t("designer.systemReadOnly") : t("designer.readOnly")} />
              {initial.capabilities.edit_templates && (
                <button type="button" className="button-primary" onClick={() => void duplicateSystem()}>
                  {t("library.customize")}
                </button>
              )}
            </div>
          )}
          {saveState === "conflict" && (
            <div className="studio-readonly">
              <StatusBanner tone="error" message={t("designer.conflict")} />
              <button type="button" className="button-secondary" onClick={() => void reloadAfterConflict()}>
                {t("designer.conflictReload")}
              </button>
              <button type="button" className="button-danger" onClick={() => void save(true)}>
                {t("designer.conflictOverwrite")}
              </button>
            </div>
          )}
          <div className={`studio-workspace studio-workspace-${view}`}>
            <LeftPanel onInsert={insertAtSelection} />
            <main ref={centerRef} className="studio-center" aria-label={t("designer.workspace")}>
              {view !== "preview" && <Canvas zoom={zoom} />}
              {view !== "design" && <PreviewPanel brandId={template.brand_id} onDiagnostics={setPreviewDiagnostics} />}
            </main>
            <aside className="studio-right" aria-label={t("props.title")}>
              {selectedId && locate(content, selectedId) ? (
                <PropertiesPanel />
              ) : (
                <DocumentPanel brandId={template.brand_id} brandMode={brandMode} onBrandChange={(id) => void changeBrand(id)} onBrandModeChange={setBrandMode} brandLocked={!!template.published_revision && !initial.capabilities.publish_templates} />
              )}
            </aside>
          </div>
        </div>
      </DndContext>
    </DesignerProvider>
  );
}
