import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { PartnerHistoryEntry, PublicLinkItem } from "@/types/api";
import { PublicLinksOverview, linkGroup } from "./public-links-overview";

const api = vi.hoisted(() => vi.fn());
const showToast = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api/client", () => ({ browserApiFetch: api }));
vi.mock("@/contexts/toast-context", () => ({ useToast: () => showToast }));

const link = (overrides: Partial<PublicLinkItem>): PublicLinkItem => ({
  kind: "share_files", id: "l1", label: "datei", params: { count: 1 }, created_at: "2026-10-15T10:00:00Z", created_by: "Timo Weber",
  expiry: "never", expires_at: null, last_used_at: null, manage_href: "/shared-links", ...overrides,
});

const LINKS: PublicLinkItem[] = [
  link({}),
  link({ kind: "submission_link", id: "s1", label: "Standard", params: { count: 0, assignments: "" }, expiry: "window", manage_href: "/submission-assignments" }),
  link({ kind: "calendar_todos", id: "c1", label: "hocX – Todos", params: { person: "Anna", scope: "own" }, manage_href: null, last_used_at: "2026-11-17T08:00:00Z" }),
  link({ kind: "album_partner", id: "a1:9", label: "Sommerlager 2026", params: { partner: "Pfadi Falkenstein", status: "accepted", publicLinks: 1 }, manage_href: "/photos" }),
  link({ kind: "share_album_partner", id: "p1", label: "Lager-Rückblick", params: { partner: "Pfadi Falkenstein", album: "Sommerlager 2026", count: 3 }, expiry: "date", expires_at: "2026-12-31T00:00:00Z", manage_href: null }),
];

const HISTORY: PartnerHistoryEntry[] = [
  { at: "2026-11-19T19:14:00Z", event: "public_link_created", actor: "partner", partner: "Pfadi Falkenstein", person: null, album: "Sommerlager 2026", link_name: "Lager-Rückblick", expires_at: "2026-12-31T00:00:00Z" },
  { at: "2026-11-02T09:00:00Z", event: "accepted", actor: "partner", partner: "Cevi Nord", person: null, album: "Chilbi 2026", link_name: null, expires_at: null },
  { at: "2026-11-01T09:00:00Z", event: "invited", actor: "own", partner: "Cevi Nord", person: "Timo Weber", album: "Chilbi 2026", link_name: null, expires_at: null },
];

function rows() {
  return screen.queryAllByRole("listitem").filter((item) => item.classList.contains("public-links-row"));
}

beforeEach(() => {
  api.mockReset();
  showToast.mockReset();
});

describe("PublicLinksOverview", () => {
  it("ordnet Partner-Links den Partner-Organisationen zu", () => {
    expect(linkGroup("share_album_partner")).toBe("partners");
    expect(linkGroup("share_album")).toBe("files");
    expect(linkGroup("album_partner")).toBe("partners");
  });

  it("zeigt Reiter mit Zählern und filtert die Zeilen", () => {
    render(<PublicLinksOverview links={LINKS} history={HISTORY} />);
    const tabs = screen.getAllByRole("tab");
    expect(tabs[0]).toHaveTextContent("Alle5");
    expect(screen.getByRole("tab", { name: /Partner-Organisationen/ })).toHaveTextContent("2");
    expect(rows()).toHaveLength(5);

    fireEvent.click(screen.getByRole("tab", { name: /Kalender/ }));
    expect(rows()).toHaveLength(1);
    expect(screen.getByText("hocX – Todos")).toBeInTheDocument();
    expect(screen.getByText("genutzt 17.11.", { exact: false })).toBeInTheDocument();
    expect(screen.getByText("nur die Person selbst")).toBeInTheDocument();
    // Verlauf erscheint nur im Partner-Reiter
    expect(screen.queryByText("Verlauf der Partner-Organisationen")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: /Konten/ }));
    expect(screen.getByText("Keine Links in dieser Auswahl.")).toBeInTheDocument();
  });

  it("zeigt den Hinweis zu Links ohne Ablauf und filtert auf diese", () => {
    render(<PublicLinksOverview links={LINKS} />);
    expect(screen.getByText("3 Links laufen nicht von selbst ab.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Nur diese zeigen" }));
    expect(rows()).toHaveLength(3);
    expect(screen.queryByText("Standard")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Alle zeigen" }));
    expect(rows()).toHaveLength(5);
  });

  it("zeigt keinen Hinweis, wenn alle Links ablaufen", () => {
    render(<PublicLinksOverview links={[LINKS[1]]} />);
    expect(screen.queryByText(/nicht von selbst ab/)).not.toBeInTheDocument();
  });

  it("bestätigt das Widerrufen inline, entfernt die Zeile und meldet es", async () => {
    api.mockResolvedValue(undefined);
    render(<PublicLinksOverview links={LINKS} />);
    // eigene Datei-/Album-Links und Partner-Links auf eigene Alben sind hier widerrufbar
    expect(screen.getAllByRole("button", { name: "Widerrufen" })).toHaveLength(2);
    const partnerRow = screen.getByText("Lager-Rückblick").closest("li") as HTMLElement;
    expect(within(partnerRow).getByRole("button", { name: "Widerrufen" })).toBeInTheDocument();
    const row = screen.getByText("datei").closest("li") as HTMLElement;
    fireEvent.click(within(row).getByRole("button", { name: "Widerrufen" }));
    expect(within(row).getByText(/«datei» widerrufen\? Wer den Link hat/)).toBeInTheDocument();

    fireEvent.click(within(row).getByRole("button", { name: "Abbrechen" }));
    expect(within(row).queryByText(/Wer den Link hat/)).not.toBeInTheDocument();

    fireEvent.click(within(row).getByRole("button", { name: "Widerrufen" }));
    const confirm = within(row).getByRole("group");
    fireEvent.click(within(confirm).getByRole("button", { name: "Widerrufen" }));
    await waitFor(() => expect(screen.queryByText("datei")).not.toBeInTheDocument());
    expect(api).toHaveBeenCalledWith("/api/share-links/l1", { method: "DELETE" });
    expect(showToast).toHaveBeenCalledWith("«datei» widerrufen", "success");
  });

  it("schliesst eine offene Bestätigung beim Reiterwechsel", () => {
    render(<PublicLinksOverview links={LINKS} />);
    fireEvent.click(screen.getAllByRole("button", { name: "Widerrufen" })[0]);
    expect(screen.getByText(/Wer den Link hat/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: /Dateien/ }));
    expect(screen.queryByText(/Wer den Link hat/)).not.toBeInTheDocument();
  });

  it("bietet ohne sharing.public kein Widerrufen an", () => {
    render(<PublicLinksOverview links={LINKS} canRevoke={false} />);
    expect(screen.queryByRole("button", { name: "Widerrufen" })).not.toBeInTheDocument();
  });

  it("zeigt den Partner-Verlauf mit Partner-Filter", () => {
    render(<PublicLinksOverview links={LINKS} history={HISTORY} />);
    fireEvent.click(screen.getByRole("tab", { name: /Partner-Organisationen/ }));
    expect(screen.getByText("Verlauf der Partner-Organisationen")).toBeInTheDocument();
    expect(screen.getByText("Öffentlichen Link «Lager-Rückblick» erstellt, gültig bis 31.12.2026")).toBeInTheDocument();
    expect(screen.getByText("Album mit Cevi Nord geteilt – Einladung gesendet")).toBeInTheDocument();
    expect(screen.getByText("Timo Weber (ihr)")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Organisation › Verlauf" })).toHaveAttribute("href", "/tenant-settings/activity");
    // im Partner-Reiter kein «Verlauf»-Sprung
    expect(screen.queryByRole("button", { name: "Verlauf" })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Cevi Nord" }));
    expect(screen.getByRole("button", { name: "Cevi Nord" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.queryByText(/Lager-Rückblick» erstellt/)).not.toBeInTheDocument();
    expect(screen.getByText("Freigabe angenommen")).toBeInTheDocument();
  });

  it("springt über «Verlauf» in den Partner-Reiter mit gewähltem Partner", () => {
    render(<PublicLinksOverview links={LINKS} history={HISTORY} />);
    const row = screen.getByText("Sommerlager 2026").closest("li") as HTMLElement;
    fireEvent.click(within(row).getByRole("button", { name: "Verlauf" }));
    expect(screen.getByRole("tab", { name: /Partner-Organisationen/ })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("button", { name: "Pfadi Falkenstein" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.queryByText("Album mit Cevi Nord geteilt – Einladung gesendet")).not.toBeInTheDocument();
  });

  it("verlinkt den Verlauf ohne activity.read nicht", () => {
    render(<PublicLinksOverview links={LINKS} history={HISTORY} canOpenActivity={false} />);
    fireEvent.click(screen.getByRole("tab", { name: /Partner-Organisationen/ }));
    expect(screen.queryByRole("link", { name: "Organisation › Verlauf" })).not.toBeInTheDocument();
    expect(screen.getByText(/Ohne IP- und E-Mail-Adressen/)).toBeInTheDocument();
  });
});
