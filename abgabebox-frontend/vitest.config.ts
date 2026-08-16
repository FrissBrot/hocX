import { defineConfig } from "vitest/config";
import path from "node:path";

// Minimal Vitest setup (audit A5, 2026-08-16 - this app had no test infra at all before).
// No jsdom/React plugin: the first tests here (lib/validate-upload.ts) are plain functions,
// nothing DOM-dependent - added only if/when a test actually needs to render a component.
export default defineConfig({
  test: {
    include: ["**/*.test.{ts,tsx}"],
    exclude: ["node_modules/**", ".next/**"],
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "."),
    },
  },
});
