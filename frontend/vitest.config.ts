import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import path from "node:path";

// Minimal Vitest setup - deliberately NOT part of the Next.js/Turbopack build pipeline
// (separate config, separate `npm run test` script). See tsconfig.json's `exclude` for why
// test files themselves are kept out of the production `tsc --noEmit` / `next build` type
// checks: vitest's ambient types (e.g. `vi`, ImportMeta.env) aren't relevant to app code and
// must never affect it.
export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    // Deliberately no `globals: true` - test files import describe/it/expect/vi explicitly
    // from "vitest" instead, so they type-check under the *default* app tsconfig without
    // needing a "vitest/globals" ambient-types entry there (which would leak vitest's global
    // types into production app code type-checking too).
    setupFiles: ["./vitest.setup.ts"],
    include: ["**/*.test.{ts,tsx}"],
    exclude: ["node_modules/**", ".next/**"],
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "."),
    },
  },
});
