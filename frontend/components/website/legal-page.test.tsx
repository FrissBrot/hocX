import fs from "node:fs";
import path from "node:path";

import { render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { defaultLocale, locales } from "@/i18n/locale-config.generated";

import { LEGAL_UPDATED, LegalPage, type LegalKind, type LegalSections } from "./legal-page";

// Rechtstexte der Website: Rendern in jeder registrierten Sprache ohne fehlende Schlüssel,
// Inhaltsverzeichnis mit Ankern, gleiche Abschnitte (Anker) in allen Sprachen.

const state = vi.hoisted(() => ({ locale: "de", host: "www.example.ch", errors: [] as string[] }));

function loadMessages(locale: string): Record<string, unknown> {
  const dir = path.join(__dirname, "..", "..", "messages", locale);
  const messages: Record<string, unknown> = {};
  for (const name of fs.readdirSync(dir)) {
    if (name.endsWith(".json")) messages[name.slice(0, -5)] = JSON.parse(fs.readFileSync(path.join(dir, name), "utf-8"));
  }
  return messages;
}

vi.mock("next-intl/server", async (importOriginal) => {
  const actual = await importOriginal<typeof import("next-intl/server")>();
  const { createTranslator } = await import("next-intl");
  return {
    ...actual,
    getTranslations: async (namespace?: string) =>
      createTranslator({
        locale: state.locale,
        messages: loadMessages(state.locale),
        namespace,
        onError: (error) => state.errors.push(String(error.code ?? error.message)),
      }),
    getLocale: async () => state.locale,
  };
});

vi.mock("next/headers", () => ({ headers: async () => new Headers({ host: state.host }) }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh: vi.fn() }) }));

afterEach(() => {
  state.errors = [];
  state.locale = "de";
  vi.unstubAllEnvs();
});

const KINDS: LegalKind[] = ["privacy", "terms"];

function sectionsOf(locale: string, kind: LegalKind): LegalSections {
  return ((loadMessages(locale).legal as Record<string, { sections: LegalSections }>)[kind]).sections;
}

function shape(sections: LegalSections): unknown {
  return Object.entries(sections).map(([id, section]) => [
    id,
    Object.entries(section).map(([key, value]) => (typeof value === "string" ? key : [key, Object.keys(value)])),
  ]);
}

describe("LegalPage", () => {
  for (const kind of KINDS) {
    for (const locale of locales) {
      it(`rendert ${kind} auf ${locale} ohne MISSING_MESSAGE, mit Ankern`, async () => {
        state.locale = locale;
        vi.stubEnv("TRAEFIK_WEBSITE_DOMAIN", "www.example.ch");
        const { container } = render(await LegalPage({ kind }));
        expect(state.errors).toEqual([]);
        expect(container.textContent).not.toMatch(/MISSING_MESSAGE|legal\.(privacy|terms|common)\./);

        expect(screen.getByRole("heading", { level: 1 })).toBeInTheDocument();
        const toc = container.querySelector("nav.ws-legal-toc") as HTMLElement;
        const links = within(toc).getAllByRole("link");
        const ids = Object.keys(sectionsOf(locale, kind));
        expect(links.map((link) => link.getAttribute("href"))).toEqual(ids.map((id) => `#${id}`));
        for (const id of ids) {
          const section = container.querySelector(`section#${id}`);
          expect(section, id).not.toBeNull();
          expect(section?.querySelector("h2")?.textContent).toBeTruthy();
        }

        // Massgebend ist die deutsche Fassung: Hinweis nur in den Übersetzungen
        expect(container.querySelector(".ws-legal-authoritative") !== null).toBe(locale !== defaultLocale);
        // Kontakt und gegenseitige Verlinkung (auf der Website-Domain ohne /website-Präfix)
        expect(container.querySelector('a[href="mailto:info@hocx.ch"]')).not.toBeNull();
        const other = kind === "privacy" ? "/terms" : "/privacy";
        expect(container.querySelector(`footer a[href="${other}"]`)).not.toBeNull();
        expect(container.querySelector(`.ws-legal-see-also a[href="${other}"]`)).not.toBeNull();
      });
    }

    it(`${kind}: alle Sprachen haben dieselben Abschnitte und Bausteine wie Deutsch`, () => {
      const reference = shape(sectionsOf(defaultLocale, kind));
      for (const locale of locales) expect(shape(sectionsOf(locale, kind)), locale).toEqual(reference);
    });
  }

  it("verlinkt ausserhalb der Website-Domain unter /website", async () => {
    vi.stubEnv("TRAEFIK_WEBSITE_DOMAIN", "www.example.ch");
    state.host = "localhost";
    const { container } = render(await LegalPage({ kind: "privacy" }));
    state.host = "www.example.ch";
    expect(container.querySelector('footer a[href="/website/terms"]')).not.toBeNull();
    expect(container.querySelector('header a.ws-brand')?.getAttribute("href")).toBe("/website");
  });

  it("zeigt den Stand und hebt Platzhalter hervor", async () => {
    const { container } = render(await LegalPage({ kind: "privacy" }));
    expect(container.textContent).toContain(LEGAL_UPDATED.privacy.slice(0, 4));
    for (const mark of Array.from(container.querySelectorAll("mark.ws-legal-placeholder"))) {
      expect(mark.textContent).toMatch(/^\[\[BITTE ERGÄNZEN/);
    }
  });

  it("enthält für Google den Hinweis zur Limited-Use-Policy mit Link", async () => {
    state.locale = "en";
    const { container } = render(await LegalPage({ kind: "privacy" }));
    expect(container.textContent).toContain(
      "hocX's use and transfer of information received from Google APIs will adhere to the Google API Services User Data Policy, including the Limited Use requirements:"
    );
    expect(container.querySelector('a[href="https://developers.google.com/terms/api-services-user-data-policy"]')).not.toBeNull();
  });
});
