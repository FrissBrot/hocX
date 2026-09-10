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
