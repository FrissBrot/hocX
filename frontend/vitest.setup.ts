import "@testing-library/jest-dom/vitest";

import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

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
