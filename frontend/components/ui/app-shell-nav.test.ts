import { describe, expect, it } from "vitest";

import { buildNav, formatRoleLabel, isNavLinkActive } from "./app-shell-nav";
import { locales } from "@/i18n/locale-config.generated";
import deNav from "@/messages/de/nav.json";
import enNav from "@/messages/en/nav.json";
import frNav from "@/messages/fr/nav.json";
import itNav from "@/messages/it/nav.json";
import type { SessionInfo } from "@/types/api";

const CATALOGS: Record<string, Record<string, unknown>> = { de: deNav, en: enNav, fr: frNav, it: itNav };

function flatten(obj: Record<string, unknown>, prefix = ""): Record<string, string> {
  return Object.entries(obj).reduce<Record<string, string>>((acc, [key, value]) => {
    const path = prefix ? `${prefix}.${key}` : key;
    if (value && typeof value === "object") {
      Object.assign(acc, flatten(value as Record<string, unknown>, path));
    } else {
      acc[path] = String(value);
    }
    return acc;
  }, {});
}

function translatorFor(locale: string) {
  const flat = flatten(CATALOGS[locale]);
  return (key: string) => flat[key] ?? key;
}

function adminSession(): SessionInfo {
  return {
    authenticated: true,
    user: { id: "u1", first_name: "A", last_name: "B", display_name: "A B", email: "a@b.ch", preferred_language: "de", protocol_accordion_enabled: true },
    current_tenant: { id: "t1", name: "Tenant", profile_image_path: null, profile_image_url: null, enabled_features: ["finance", "abgabebox"] },
    current_role: "admin",
  } as unknown as SessionInfo;
}

describe("formatRoleLabel", () => {
  it.each(locales)("uebersetzt jede bekannte Rolle in '%s', ohne auf die Rollenkonstante zurueckzufallen", (locale) => {
    const t = translatorFor(locale);
    for (const role of ["admin", "writer", "kassier", "reader"]) {
      const label = formatRoleLabel(role, t);
      expect(label).not.toBe(role);
      expect(label.length).toBeGreaterThan(0);
    }
  });

  it("gibt die Rolle selbst zurueck, wenn sie unbekannt ist", () => {
    const t = translatorFor("de");
    expect(formatRoleLabel("ghost-role", t)).toBe("ghost-role");
  });

  it("faellt bei fehlender Rolle auf den Status-Text zurueck", () => {
    const t = translatorFor("de");
    expect(formatRoleLabel(null, t)).toBe(t("roles.status"));
  });
});

describe("buildNav", () => {
  it("liefert fuer eine Admin-Session alle Gruppen mit uebersetzbaren labelKey/titleKey (keine fertigen Texte)", () => {
    const groups = buildNav(adminSession());
    expect(groups.length).toBeGreaterThan(1);
    for (const group of groups) {
      for (const link of group.links) {
        expect(typeof link.labelKey).toBe("string");
        // labelKey ist ein Uebersetzungs-Key (kurz, camelCase), kein fertiger Satz.
        expect(link.labelKey).toMatch(/^[a-zA-Z.]+$/);
      }
    }
  });

  it.each(locales)("jeder Navigationseintrag loest in '%s' zu einem nicht-leeren, uebersetzten Label auf", (locale) => {
    const t = translatorFor(locale);
    const groups = buildNav(adminSession());
    for (const group of groups) {
      if (group.titleKey) {
        expect(t(group.titleKey)).not.toBe(group.titleKey);
      }
      for (const link of group.links) {
        expect(t(link.labelKey)).not.toBe(link.labelKey);
      }
    }
  });

  it("isNavLinkActive erkennt die aktive Route unabhaengig von der Sprache (reine Pfadlogik)", () => {
    const groups = buildNav(adminSession());
    const dashboardLink = groups[0].links[0];
    expect(isNavLinkActive(dashboardLink, "/")).toBe(true);
    expect(isNavLinkActive(dashboardLink, "/statistics")).toBe(true);
    expect(isNavLinkActive(dashboardLink, "/participants")).toBe(false);
  });
});
