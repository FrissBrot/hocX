import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { PhotosNoResults, PhotosPageHeader, PhotosToolbar } from "./photos-header";

// Tausendertrennung wie in der App (de-CH), je nach ICU-Version ' oder ’
const N1553 = new Intl.NumberFormat("de-CH").format(1553);

const SORT_OPTIONS = [
  { id: "auto", label: "Beste Treffer" },
  { id: "group_date:desc", label: "Neueste zuerst" },
];

function renderToolbar(overrides: Partial<Parameters<typeof PhotosToolbar>[0]> = {}) {
  const props = {
    tab: "all" as const,
    onTabChange: vi.fn(),
    search: "",
    onSearchChange: vi.fn(),
    showSort: true,
    sortOptions: SORT_OPTIONS,
    sortId: "auto",
    onSortChange: vi.fn(),
    showTags: true,
    tags: [] as string[],
    onTagsChange: vi.fn(),
    tagSuggestions: ["Sommerlager"],
    resultCount: null,
    total: 1553,
    activeSearch: "",
    onReset: vi.fn(),
    ...overrides,
  };
  render(<PhotosToolbar {...props} />);
  return props;
}

describe("PhotosPageHeader", () => {
  it("zeigt Titel, Zähler mit Schweizer Tausendertrennung, Papierkorb und Hochladen", () => {
    const onUpload = vi.fn();
    const onOpenTrash = vi.fn();
    render(<PhotosPageHeader total={1553} onUpload={onUpload} onOpenTrash={onOpenTrash} />);

    expect(screen.getByRole("heading", { name: "Fotos" })).toBeInTheDocument();
    expect(screen.getByLabelText(/^1\D?553 Fotos$/)).toHaveTextContent(N1553);
    fireEvent.click(screen.getByRole("button", { name: "Bilder hochladen" }));
    fireEvent.click(screen.getByRole("button", { name: "Papierkorb" }));
    expect(onUpload).toHaveBeenCalled();
    expect(onOpenTrash).toHaveBeenCalled();
  });

  it("ohne Recht kein Papierkorb, ohne Zahl kein Zähler", () => {
    render(<PhotosPageHeader total={null} onUpload={vi.fn()} />);
    expect(screen.queryByRole("button", { name: "Papierkorb" })).not.toBeInTheDocument();
    expect(screen.queryByText(N1553)).not.toBeInTheDocument();
  });
});

describe("PhotosToolbar", () => {
  it("hat Reiter, Suche, Sortierung und Tags; ohne Filter keine Statuszeile", () => {
    renderToolbar();
    expect(screen.getByRole("tab", { name: "Alle Fotos" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tab", { name: "Duplikate" })).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Fotos durchsuchen" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Sortierung: Beste Treffer" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Tags" })).toBeInTheDocument();
    expect(screen.queryByText("Filter zurücksetzen")).not.toBeInTheDocument();
  });

  it("meldet Tippen und leert die Suche über den runden Knopf", () => {
    const props = renderToolbar({ search: "stadt game" });
    fireEvent.change(screen.getByRole("textbox", { name: "Fotos durchsuchen" }), { target: { value: "stadt gam" } });
    expect(props.onSearchChange).toHaveBeenLastCalledWith("stadt gam");
    fireEvent.click(screen.getByRole("button", { name: "Suche leeren" }));
    expect(props.onSearchChange).toHaveBeenLastCalledWith("");
  });

  it("zeigt bei aktiver Suche Anzahl, Chips und «Filter zurücksetzen»", () => {
    const props = renderToolbar({ search: "stadt game", activeSearch: "stadt game", tags: ["Sola"], resultCount: 0 });
    expect(screen.getByText(`0 von ${N1553} Fotos`)).toBeInTheDocument();
    expect(screen.getByText("„stadt game“")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Tag «Sola» entfernen" }));
    expect(props.onTagsChange).toHaveBeenCalledWith([]);
    fireEvent.click(screen.getByRole("button", { name: "Filter zurücksetzen" }));
    expect(props.onReset).toHaveBeenCalled();
  });

  it("wählt die Sortierung im Menü", () => {
    const props = renderToolbar();
    fireEvent.click(screen.getByRole("button", { name: "Sortierung: Beste Treffer" }));
    fireEvent.click(screen.getByRole("menuitemradio", { name: "Neueste zuerst" }));
    expect(props.onSortChange).toHaveBeenCalledWith("group_date:desc");
  });

  it("blendet Suche, Sortierung und Tags im Reiter Alben aus", () => {
    renderToolbar({ tab: "albums" });
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Tags" })).not.toBeInTheDocument();
  });
});

describe("PhotosNoResults", () => {
  it("nennt den Suchbegriff und bietet das Zurücksetzen an", () => {
    const onReset = vi.fn();
    render(<PhotosNoResults query=" stadt game " onReset={onReset} />);
    expect(screen.getByText("Keine Fotos für „stadt game“")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "setze die Filter zurück" }));
    expect(onReset).toHaveBeenCalled();
  });
});
