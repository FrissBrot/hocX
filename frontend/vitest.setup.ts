import "@testing-library/jest-dom/vitest";

import fs from "node:fs";
import path from "node:path";
import { cleanup } from "@testing-library/react";
import { afterEach, vi } from "vitest";

// Component tests render UI components directly (no NextIntlClientProvider - they're not
// exercising the root layout), but most components now call useTranslations()/useLocale()
// internally. Rather than wrapping every render() call across the whole suite, this mocks
// next-intl's hooks with its own non-React createTranslator() against the real `de` message
// catalogs - so existing assertions against specific German strings (e.g. "Widerrufen", "Kein
// Gesicht erkannt") keep passing unchanged, and newly migrated components "just work" in tests
// without each one needing a provider wrapper. Dedicated i18n tests (see i18n.test.ts) cover
// the other locales and the provider wiring itself.
const messagesDir = path.join(__dirname, "messages", "de");
const deMessages: Record<string, unknown> = {};
for (const entry of fs.readdirSync(messagesDir, { withFileTypes: true })) {
  if (entry.isFile() && entry.name.endsWith(".json")) {
    deMessages[entry.name.slice(0, -".json".length)] = JSON.parse(
      fs.readFileSync(path.join(messagesDir, entry.name), "utf-8")
    );
  }
}

vi.mock("next-intl", async (importOriginal) => {
  const actual = await importOriginal<typeof import("next-intl")>();
  return {
    ...actual,
    useTranslations: (namespace?: string) =>
      actual.createTranslator({ locale: "de", messages: deMessages, namespace }),
    useLocale: () => "de",
  };
});

// Server Components (async page.tsx without "use client") call getTranslations()/getLocale()
// from "next-intl/server" instead of the hooks above - that module relies on Next's real RSC
// request context, which doesn't exist when a test calls such a page function directly (e.g.
// `render(await SomePage(props))`), surfacing as "getTranslations is not supported in Client
// Components" even though the page is a perfectly ordinary Server Component. Mocked the same
// way as the client hooks above, against the same real `de` catalogs.
vi.mock("next-intl/server", async (importOriginal) => {
  const actual = await importOriginal<typeof import("next-intl/server")>();
  const { createTranslator } = await import("next-intl");
  return {
    ...actual,
    getTranslations: async (namespace?: string) =>
      createTranslator({ locale: "de", messages: deMessages, namespace }),
    getLocale: async () => "de",
    getMessages: async () => deMessages,
  };
});

// Not automatic here: with `globals: true` disabled (see vitest.config.ts), Testing Library's
// own auto-cleanup never registers (it only self-attaches to a *global* afterEach). Without
// this, every render() in a component test file would pile onto the same jsdom document
// instead of unmounting between tests.
afterEach(() => {
  cleanup();
});

// jsdom has no IntersectionObserver. Test files that care stub their own via
// vi.stubGlobal (and vi.unstubAllGlobals() then restores *this* no-op, not "undefined"), but a
// React passive effect (e.g. PhotoTile's lazy-load observer) can still run after such a test's
// afterEach - on a slow CI runner that surfaced as "ReferenceError: IntersectionObserver is not
// defined" in an otherwise unrelated test. A no-op default keeps those stragglers harmless.
if (typeof globalThis.IntersectionObserver === "undefined") {
  class NoopIntersectionObserver implements IntersectionObserver {
    readonly root = null;
    readonly rootMargin = "0px";
    readonly thresholds: readonly number[] = [];
    observe() {}
    unobserve() {}
    disconnect() {}
    takeRecords(): IntersectionObserverEntry[] {
      return [];
    }
  }
  globalThis.IntersectionObserver = NoopIntersectionObserver;
}
