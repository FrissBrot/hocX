import { afterEach, describe, expect, it, vi } from "vitest";

import deNav from "@/messages/de/nav.json";
import deSearch from "@/messages/de/search.json";
import { SYSTEM_ROLE_PERMISSIONS, type SystemRoleKey } from "@/lib/permissions.generated";
import type { SessionInfo } from "@/types/api";

import { clearOpenRequest, readOpenRequest, storeSearchHandoff } from "./handoff";
import { findListSearchInput, focusListSearch } from "./list-search";
import { foldText, matchScore, rankEntries } from "./match";
import { buildStaticEntries } from "./static-entries";

function flatten(obj: Record<string, unknown>, prefix = ""): Record<string, string> {
  return Object.entries(obj).reduce<Record<string, string>>((acc, [key, value]) => {
    const path = prefix ? `${prefix}.${key}` : key;
    if (value && typeof value === "object") Object.assign(acc, flatten(value as Record<string, unknown>, path));
    else acc[path] = String(value);
    return acc;
  }, {});
}

function translator(catalog: Record<string, unknown>) {
  const flat = flatten(catalog);
  const t = ((key: string) => flat[key] ?? key) as ((key: string) => string) & { has: (key: string) => boolean };
  t.has = (key: string) => key in flat;
  return t;
}

const tNav = translator(deNav);
const tSearch = translator(deSearch);

function sessionFor(role: SystemRoleKey): SessionInfo {
  return {
    authenticated: true,
    user: { id: "u1", display_name: "A B" },
    current_tenant: { id: "t1", name: "Verein", enabled_features: ["finance", "abgabebox"] },
    permissions: [...SYSTEM_ROLE_PERMISSIONS[role]],
    roles: [{ id: `r-${role}`, name: null, system_key: role }],
  } as unknown as SessionInfo;
}

describe("matchScore", () => {
  it("ignoriert Gross-/Kleinschreibung, Umlaute und Akzente", () => {
    expect(foldText("Müller Ärger Café")).toBe("muller arger cafe");
    expect(matchScore({ label: "Bussen-Konfiguration" }, "bussen")).toBeGreaterThan(0);
    expect(matchScore({ label: "Datenschutz" }, "DATENSCHÜTZ")).toBeGreaterThan(0);
  });

  it("verlangt jedes Wort und bewertet Titelanfang vor Suchbegriffen", () => {
    expect(matchScore({ label: "Rollen", keywords: "Rechte" }, "rollen rechte")).toBeGreaterThan(0);
    expect(matchScore({ label: "Rollen" }, "rollen kasse")).toBe(0);
    const ranked = rankEntries([{ label: "Konten", keywords: "Benutzer" }, { label: "Benutzerrollen" }], "benutzer");
    expect(ranked.map((entry) => entry.label)).toEqual(["Benutzerrollen", "Konten"]);
  });
});

describe("buildStaticEntries", () => {
  it("findet Einstellungen über Suchbegriffe, nur mit Berechtigung", () => {
    const admin = buildStaticEntries(sessionFor("admin"), tNav, tSearch);
    const privacy = rankEntries(admin, "dsgvo");
    expect(privacy[0]).toMatchObject({ href: "/tenant-settings/privacy", group: "settings" });
    expect(rankEntries(admin, "rechte")[0]).toMatchObject({ href: "/users/roles" });

    const reader = buildStaticEntries(sessionFor("reader"), tNav, tSearch);
    expect(reader.some((entry) => entry.href?.startsWith("/tenant-settings"))).toBe(false);
    expect(reader.some((entry) => entry.href === "/users")).toBe(false);
    // Profil und Darstellung gibt es für alle
    expect(rankEntries(reader, "passwort")[0]).toMatchObject({ action: "profile" });
    expect(rankEntries(reader, "dunkel")[0]).toMatchObject({ action: "theme-dark" });
  });

  it("führt jede Seite nur einmal", () => {
    // Einzelne Einstellungen dürfen in denselben Abschnitt springen (z. B. Name, Bild und Adresse)
    const entries = buildStaticEntries(sessionFor("admin"), tNav, tSearch);
    const hrefs = entries.filter((entry) => entry.href && !entry.id.startsWith("setting:")).map((entry) => entry.href);
    expect(new Set(hrefs).size).toBe(hrefs.length);
    const ids = entries.map((entry) => entry.id);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it("findet alle Einstellungen, obwohl sie nicht mehr in der Seitenleiste stehen", () => {
    const entries = buildStaticEntries(sessionFor("admin"), tNav, tSearch);
    const settingsHrefs = entries.filter((entry) => entry.group === "settings").map((entry) => entry.href);
    for (const href of ["/settings", "/templates", "/task-packages", "/fine-settings", "/users", "/documents", "/documents/brand",
      "/tenant-settings/domains", "/tenant-settings", "/tenant-settings/abo", "/tenant-settings/privacy", "/tenant-settings/retention",
      "/tenant-settings/links", "/shared-links", "/tenant-settings/activity", "/tools/import"]) {
      expect(settingsHrefs).toContain(href);
    }
    expect(rankEntries(entries, "einstellungen")[0]).toMatchObject({ href: "/settings" });
    // Arbeitsbereiche bleiben «Seiten»
    expect(entries.find((entry) => entry.href === "/fines")?.group).toBe("pages");
  });
});

describe("Listensuche", () => {
  afterEach(() => {
    document.body.innerHTML = "";
  });

  function visible(element: HTMLElement) {
    element.getClientRects = () => [{}] as unknown as DOMRectList;
  }

  function mount(html: string) {
    document.body.innerHTML = html;
    document.querySelectorAll<HTMLElement>("*").forEach(visible);
  }

  it("nimmt das Suchfeld im Seiteninhalt, im offenen Dialog aber nur dessen eigenes", () => {
    mount('<div class="shell-content"><div class="search-input"><input id="page" /></div></div>');
    expect(findListSearchInput()?.id).toBe("page");

    mount('<div class="shell-content"><div class="search-input"><input id="page" /></div></div><div role="dialog"><p>ohne Suche</p></div>');
    expect(findListSearchInput()).toBeNull();

    mount('<div class="shell-content"><div class="search-input"><input id="page" /></div></div><div role="dialog"><div class="search-input"><input id="modal" /></div></div>');
    expect(findListSearchInput()?.id).toBe("modal");
  });

  it("übergeht das Suchfenster selbst und ausgenommene Felder", () => {
    mount('<div class="shell-content"><div data-list-search="off"><div class="search-input"><input id="off" /></div></div></div><div role="dialog"><div data-global-search><div class="search-input"><input id="palette" /></div></div></div>');
    expect(findListSearchInput()).toBeNull();
  });

  it("setzt den Text so, dass ein React-onChange ihn bekommt", () => {
    mount('<div class="shell-content"><div class="search-input"><input id="page" /></div></div>');
    const input = document.getElementById("page") as HTMLInputElement;
    const seen: string[] = [];
    input.addEventListener("input", () => seen.push(input.value));
    focusListSearch(input, "anna");
    expect(seen).toEqual(["anna"]);
    expect(document.activeElement).toBe(input);
  });
});

describe("Übergabe an die Zielseite", () => {
  it("liest ?open= mit dem Suchtext aus sessionStorage und räumt beides weg", () => {
    window.history.replaceState(null, "", "/files?open=abc&x=1");
    storeSearchHandoff({ id: "abc", search: "Statuten.pdf" });
    expect(readOpenRequest()).toEqual({ id: "abc", search: "Statuten.pdf" });
    // Lesen allein löscht nichts (mobile Ansicht kann nach der Desktop-Ansicht montiert werden)
    expect(readOpenRequest()).toEqual({ id: "abc", search: "Statuten.pdf" });
    clearOpenRequest();
    expect(window.location.search).toBe("?x=1");
    expect(readOpenRequest()).toBeNull();
    expect(window.sessionStorage.getItem("hocx-search-handoff")).toBeNull();
  });

  it("nimmt keinen Suchtext einer anderen Datei", () => {
    window.history.replaceState(null, "", "/files?open=def");
    storeSearchHandoff({ id: "abc", search: "Fremd.pdf" });
    expect(readOpenRequest()).toEqual({ id: "def", search: "" });
    clearOpenRequest();
  });
});

describe("Tastenkürzel", () => {
  afterEach(() => {
    document.body.innerHTML = "";
    vi.restoreAllMocks();
  });

  it("Ctrl+K öffnet die Suche, Ctrl+F springt in die Liste und bleibt beim zweiten Mal beim Browser", async () => {
    const { renderHook } = await import("@testing-library/react");
    const { useGlobalSearchShortcuts } = await import("./shortcuts");
    document.body.innerHTML = '<div class="shell-content"><div class="search-input"><input id="page" /></div></div>';
    const input = document.getElementById("page") as HTMLInputElement;
    input.getClientRects = () => [{}] as unknown as DOMRectList;
    const open = vi.fn();
    const hook = renderHook(() => useGlobalSearchShortcuts(open));

    const ctrlK = new KeyboardEvent("keydown", { key: "k", ctrlKey: true, cancelable: true });
    window.dispatchEvent(ctrlK);
    expect(open).toHaveBeenCalledTimes(1);
    expect(ctrlK.defaultPrevented).toBe(true);

    const first = new KeyboardEvent("keydown", { key: "f", ctrlKey: true, cancelable: true });
    window.dispatchEvent(first);
    expect(first.defaultPrevented).toBe(true);
    expect(document.activeElement).toBe(input);

    const second = new KeyboardEvent("keydown", { key: "f", ctrlKey: true, cancelable: true });
    window.dispatchEvent(second);
    expect(second.defaultPrevented).toBe(false);

    // Seiten mit eigener Suche (Protokoll-Editor) behalten Ctrl+F
    input.blur();
    document.body.insertAdjacentHTML("beforeend", "<div data-own-find></div>");
    const own = new KeyboardEvent("keydown", { key: "f", ctrlKey: true, cancelable: true });
    window.dispatchEvent(own);
    expect(own.defaultPrevented).toBe(false);
    hook.unmount();
  });
});


describe("einzelne Einstellungen", () => {
  it("erscheinen nur, wenn die Seite sichtbar ist, und springen in den Abschnitt", () => {
    const admin = buildStaticEntries(sessionFor("admin"), tNav, tSearch);
    const tariffs = admin.find((entry) => entry.id === "setting:fineTariffGroups");
    expect(tariffs?.href).toBe("/fine-settings?tab=tariffs");
    expect(tariffs?.group).toBe("settings");
    expect(rankEntries(admin, "vereinsname", 3)[0]?.id).toBe("setting:tenantName");
    expect(rankEntries(admin, "loschfristen", 5).map((entry) => entry.id)).toContain("setting:retentionRules");

    const reader = buildStaticEntries(sessionFor("reader"), tNav, tSearch);
    expect(reader.some((entry) => entry.id.startsWith("setting:tenant"))).toBe(false);
  });
});

describe("Suche in allen Sprachen und mit Tippfehlern", () => {
  async function entriesWithOtherLanguages() {
    const { crossLanguageKeywords, loadOtherLanguages } = await import("./multilingual");
    const session = sessionFor("admin");
    const extra = crossLanguageKeywords(session, await loadOtherLanguages("de"));
    return buildStaticEntries(session, tNav, tSearch).map((entry) => ({
      ...entry,
      keywords: [entry.keywords, extra.get(entry.id)].filter(Boolean).join(" "),
    }));
  }

  it("findet deutsche Einträge mit englischen und französischen Wörtern", async () => {
    const entries = await entriesWithOtherLanguages();
    const hrefs = (query: string) => rankEntries(entries, query, 20).map((entry) => entry.href);
    expect(hrefs("logs")).toContain("/tenant-settings/activity");
    expect(hrefs("settings")).toContain("/tenant-settings");
    expect(hrefs("paramètres")).toContain("/tenant-settings");
    expect(hrefs("roles")).toContain("/users/roles");
  });

  it("verzeiht einen Tippfehler, aber nur als schwächsten Treffer", () => {
    expect(matchScore({ label: "Verlauf" }, "verluaf")).toBeGreaterThan(0);
    expect(matchScore({ label: "Einstellungen" }, "einstelungen")).toBeGreaterThan(0);
    expect(matchScore({ label: "Verlauf" }, "verlauf")).toBeGreaterThan(matchScore({ label: "Verlauf" }, "verluaf"));
    // Kurze Wörter und zwei Fehler: kein Treffer
    expect(matchScore({ label: "Abo" }, "abx")).toBe(0);
    expect(matchScore({ label: "Verlauf" }, "vrluaf")).toBe(0);
  });
});

describe("highlightMatch", () => {
  it("markiert Fundstellen unabhängig von Umlauten und Gross-/Kleinschreibung", async () => {
    const { highlightMatch } = await import("./match");
    expect(highlightMatch("Küchenämtli", "kuche")).toEqual([{ text: "Küche", hit: true }, { text: "nämtli", hit: false }]);
    expect(highlightMatch("Audit-Log", "log")).toEqual([{ text: "Audit-", hit: false }, { text: "Log", hit: true }]);
    expect(highlightMatch("Strasse", "straße")).toEqual([{ text: "Strasse", hit: true }]);
    expect(highlightMatch("Jobs", "")).toEqual([{ text: "Jobs", hit: false }]);
  });
});
