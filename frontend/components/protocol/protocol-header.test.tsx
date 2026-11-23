import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/components/documents/export-dialog", () => ({
  DocumentExportDialog: ({ open }: { open: boolean }) => (open ? <div role="dialog" aria-label="Dokument exportieren" /> : null),
}));

import { ProtocolHeader } from "./protocol-header";

// Protokoll-Kopf: Schritte nur Anzeige (aria-current), Schalter «Nachverfolgen» als echter
// Switch, Hauptknopf, Export- und «⋯»-Menü, Hinweis «Vorlage geändert», Nur-Lesen ohne Aktionen.

function setup(overrides: Partial<Parameters<typeof ProtocolHeader>[0]> = {}) {
  const props = {
    title: "Vorstandssitzung",
    protocolNumber: "P-2026-014",
    createdAt: "2026-11-20T18:30:00Z",
    templateVersion: 3,
    status: "geplant",
    isReadOnly: false,
    ctaLabel: "Vorbereitung abschliessen",
    ctaBusy: false,
    onCta: vi.fn(),
    trackChanges: { visible: true, enabled: false, onChange: vi.fn() },
    templateChange: { visible: false, busy: false, onReload: vi.fn() },
    importSource: null,
    onOpenSearch: vi.fn(),
    pdf: { busy: false, onOpen: vi.fn() },
    protocolId: "p-1",
    presence: null,
    ...overrides,
  };
  render(<ProtocolHeader {...props} />);
  return props;
}

describe("ProtocolHeader", () => {
  it("zeigt Titel, Meta-Zeile und Zurück-Link", () => {
    setup();
    expect(screen.getByRole("heading", { level: 1, name: "Vorstandssitzung" })).toBeInTheDocument();
    expect(screen.getByText("P-2026-014")).toBeInTheDocument();
    expect(screen.getByText("Vorlage v3")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Zurück zu den Protokollen" })).toHaveAttribute("href", "/protocols");
  });

  it("markiert den aktuellen Schritt und erledigte Schritte, ohne sie klickbar zu machen", () => {
    setup({ status: "durchgeführt", ctaLabel: "Protokoll abschliessen", trackChanges: { visible: false, enabled: false, onChange: vi.fn() } });
    const steps = within(screen.getByRole("list", { name: "Ablauf des Protokolls" })).getAllByRole("listitem");
    expect(steps).toHaveLength(4);
    expect(steps[2]).toHaveAttribute("aria-current", "step");
    expect(steps[0]).toHaveTextContent("erledigt");
    expect(steps[1]).toHaveTextContent("erledigt");
    expect(steps[3]).not.toHaveTextContent("erledigt");
    expect(within(steps[2]).queryByRole("button")).toBeNull();
  });

  it("schaltet Nachverfolgen als Switch per Klick und Leertaste-Semantik (Checkbox)", () => {
    const props = setup();
    const toggle = screen.getByRole("switch", { name: "Nachverfolgen" });
    expect(toggle).not.toBeChecked();
    fireEvent.click(toggle);
    expect(props.trackChanges.onChange).toHaveBeenCalledWith(true);
    expect(screen.getByRole("button", { name: "Hilfe zu «Änderungen nachverfolgen»" })).toBeInTheDocument();
  });

  it("löst den Hauptknopf aus und öffnet die Suche", () => {
    const props = setup();
    fireEvent.click(screen.getByRole("button", { name: /Vorbereitung abschliessen/ }));
    expect(props.onCta).toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: /^Im Protokoll suchen/ }));
    expect(props.onOpenSearch).toHaveBeenCalled();
  });

  it("zeigt nur lesend weder Hauptknopf noch Schalter", () => {
    setup({ isReadOnly: true, status: "abgeschlossen", ctaLabel: undefined });
    expect(screen.queryByRole("switch")).toBeNull();
    expect(screen.queryByRole("button", { name: /abschliessen/ })).toBeNull();
    expect(screen.getAllByRole("listitem")[3]).toHaveTextContent("erledigt");
  });

  it("öffnet aus dem Export-Menü das PDF und den Export-Dialog", () => {
    const props = setup();
    fireEvent.click(screen.getByRole("button", { name: "Exportieren" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "PDF öffnen" }));
    expect(props.pdf.onOpen).toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Exportieren" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Exportieren …" }));
    expect(screen.getByRole("dialog", { name: "Dokument exportieren" })).toBeInTheDocument();
  });

  it("sperrt «PDF öffnen», solange das PDF erzeugt wird", () => {
    setup({ pdf: { busy: true, onOpen: vi.fn() } });
    fireEvent.click(screen.getByRole("button", { name: "Exportieren" }));
    expect(screen.getByRole("menuitem", { name: "PDF wird erstellt …" })).toBeDisabled();
  });

  it("zeigt «Originaldokument öffnen» nur mit Importquelle und die Ablauf-Hilfe", () => {
    setup();
    fireEvent.click(screen.getByRole("button", { name: "Weitere Aktionen" }));
    expect(screen.queryByRole("menuitem", { name: "Original-Dokument öffnen" })).toBeNull();
    fireEvent.click(screen.getByRole("menuitem", { name: "Hilfe zum Ablauf" }));
    expect(screen.getByRole("dialog", { name: "Status und Arbeitsmodus" })).toBeInTheDocument();
  });

  it("bietet mit Importquelle das Originaldokument an", () => {
    setup({ importSource: { url: "/api/files/original", filename: "alt.docx" } });
    fireEvent.click(screen.getByRole("button", { name: "Weitere Aktionen" }));
    expect(screen.getByRole("menuitem", { name: "Original-Dokument öffnen" })).toBeInTheDocument();
  });

  it("zeigt «Vorlage geändert» mit «Neu laden» in der Leiste", () => {
    const props = setup({ templateChange: { visible: true, busy: false, onReload: vi.fn() } });
    expect(screen.getByText("Vorlage wurde geändert")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Neu laden" }));
    expect(props.templateChange.onReload).toHaveBeenCalled();
  });
});
