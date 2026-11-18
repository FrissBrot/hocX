import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { PublicShareGallery } from "./public-share-gallery";
import { PublicShare, PublicShareFile } from "@/types/api";

function makeFile(id: string, overrides: Partial<PublicShareFile> = {}): PublicShareFile {
  return {
    id,
    original_name: `${id}.jpg`,
    mime_type: "image/jpeg",
    file_size_bytes: 100_352,
    is_image: true,
    width: 1200,
    height: 800,
    taken_at: null,
    thumbnail_url: `/api/public/share/tok/files/${id}/thumbnail`,
    view_url: `/api/public/share/tok/files/${id}/view`,
    download_url: `/api/public/share/tok/files/${id}/download`,
    ...overrides
  };
}

function makeShare(overrides: Partial<PublicShare> = {}): PublicShare {
  return {
    name: "Tag 15 – Wald, Feuer & Wiese",
    context: "Sommerlager 2026 · Val Bavona",
    is_album: true,
    tenant_name: "Jungwacht Littau",
    expires_at: "2026-10-31T12:00:00Z",
    total_size_bytes: 1_717_986_918,
    date_from: "2026-07-14T08:00:00Z",
    date_to: "2026-07-28T18:00:00Z",
    files: [makeFile("a"), makeFile("b"), makeFile("c")],
    download_all_url: "/api/public/share/tok/download",
    ...overrides
  };
}

describe("PublicShareGallery", () => {
  it("zeigt Absender, Metadaten und den ZIP-Download aller Dateien", () => {
    render(<PublicShareGallery share={makeShare()} />);

    expect(screen.getByText("Jungwacht Littau")).toBeInTheDocument();
    expect(screen.getByText("hat ein Album mit dir geteilt")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Tag 15 – Wald, Feuer & Wiese" })).toBeInTheDocument();
    expect(screen.getByText("3 Fotos")).toBeInTheDocument();
    expect(screen.getByText("1.6 GB")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Alle herunterladen \(ZIP\)/ })).toHaveAttribute("href", "/api/public/share/tok/download");
  });

  it("verlinkt hocX im Footer auf die Landingpage", () => {
    render(<PublicShareGallery share={makeShare()} />);

    expect(screen.getByRole("link", { name: "hocX" })).toHaveAttribute("href", "https://hocx.ch");
  });

  it("lädt im Auswahlmodus nur die gewählten Dateien als ZIP", () => {
    render(<PublicShareGallery share={makeShare()} />);

    fireEvent.click(screen.getByRole("button", { name: "Auswählen" }));
    expect(screen.getByText("0 ausgewählt")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Auswahl herunterladen/ })).toBeDisabled();

    fireEvent.click(screen.getByRole("button", { name: "c.jpg auswählen" }));
    fireEvent.click(screen.getByRole("button", { name: "a.jpg auswählen" }));

    expect(screen.getByText("2 ausgewählt")).toBeInTheDocument();
    // Reihenfolge des Links, nicht die Klick-Reihenfolge.
    expect(screen.getByRole("link", { name: /Auswahl herunterladen/ })).toHaveAttribute("href", "/api/public/share/tok/download?ids=a,c");

    // «Alle» wählt alles (dann ohne ?ids=), ein zweiter Klick hebt die Auswahl auf.
    fireEvent.click(screen.getByRole("button", { name: "Alle" }));
    expect(screen.getByRole("link", { name: /Auswahl herunterladen/ })).toHaveAttribute("href", "/api/public/share/tok/download");
    fireEvent.click(screen.getByRole("button", { name: "Keine" }));
    expect(screen.getByText("0 ausgewählt")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Abbrechen" }));
    expect(screen.getByRole("button", { name: "Auswählen" })).toBeInTheDocument();
  });

  it("öffnet ein Foto in der Lightbox und blättert weiter", () => {
    render(<PublicShareGallery share={makeShare()} />);

    fireEvent.click(screen.getByRole("button", { name: "a.jpg öffnen" }));
    const dialog = screen.getByRole("dialog", { name: "a.jpg" });
    expect(dialog).toBeInTheDocument();
    expect(screen.getByText(/1 von 3/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Nächstes" }));
    expect(screen.getByRole("dialog", { name: "b.jpg" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /^Herunterladen$/ })).toHaveAttribute("href", "/api/public/share/tok/files/b/download");

    fireEvent.keyDown(window, { key: "ArrowLeft" });
    expect(screen.getByRole("dialog", { name: "a.jpg" })).toBeInTheDocument();
  });

  it("zeigt Dateien als Kacheln mit Vorschau, Typ und Download und schaltet auf Liste um", () => {
    const share = makeShare({
      is_album: false,
      context: null,
      files: [
        makeFile("bericht", {
          original_name: "Bericht.pdf",
          mime_type: "application/pdf",
          is_image: false,
          width: null,
          height: null,
          view_url: null,
          page_count: 12,
          thumbnail_url: "/api/public/share/tok/files/bericht/thumbnail"
        }),
        makeFile("liste", { original_name: "Liste.csv", mime_type: "text/csv", is_image: false, thumbnail_url: null, view_url: null })
      ]
    });
    const { container } = render(<PublicShareGallery share={share} />);

    expect(screen.getByText("hat Dateien mit dir geteilt")).toBeInTheDocument();
    expect(screen.getByText("Geteilte Dateien")).toBeInTheDocument();
    expect(screen.getByText("2 Dateien")).toBeInTheDocument();
    expect(screen.getByText("PDF")).toBeInTheDocument();
    expect(screen.getByText(/12 Seiten/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Bericht.pdf herunterladen" })).toHaveAttribute("href", "/api/public/share/tok/files/bericht/download");
    expect(container.querySelector(".public-share-preview-page-tile img")).toHaveAttribute("src", "/api/public/share/tok/files/bericht/thumbnail");

    fireEvent.click(screen.getByRole("button", { name: "Liste" }));
    expect(container.querySelector(".public-share-list")).not.toBeNull();
    expect(screen.getByRole("button", { name: "Liste" })).toHaveAttribute("aria-pressed", "true");

    // Auch Dateien ohne Vorschau öffnen die Vollbild-Ansicht (mit Download statt Bild).
    fireEvent.click(screen.getByRole("button", { name: "Liste.csv öffnen" }));
    expect(screen.getByRole("dialog", { name: "Liste.csv" })).toBeInTheDocument();
    expect(screen.getByText("Für diese Datei gibt es keine Vorschau.")).toBeInTheDocument();
  });
});
