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
    expect(screen.getByRole("link", { name: /Alle herunterladen/ })).toHaveAttribute("href", "/api/public/share/tok/download");
  });

  it("verlinkt hocX im Footer auf die Landingpage", () => {
    render(<PublicShareGallery share={makeShare()} />);

    expect(screen.getByRole("link", { name: "hocX" })).toHaveAttribute("href", "https://hocx.ch");
  });

  it("lädt im Auswahlmodus nur die gewählten Dateien als ZIP", () => {
    render(<PublicShareGallery share={makeShare()} />);

    fireEvent.click(screen.getByRole("button", { name: "Auswählen" }));
    expect(screen.getByRole("button", { name: /Nichts ausgewählt/ })).toBeDisabled();

    fireEvent.click(screen.getByRole("button", { name: "c.jpg auswählen" }));
    fireEvent.click(screen.getByRole("button", { name: "a.jpg auswählen" }));

    // Reihenfolge des Links, nicht die Klick-Reihenfolge.
    expect(screen.getByRole("link", { name: /2 herunterladen/ })).toHaveAttribute("href", "/api/public/share/tok/download?ids=a,c");
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
  });
});
