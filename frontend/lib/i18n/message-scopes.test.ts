import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

import { defaultLocale } from "@/i18n/locale-config.generated";
import {
  AREA_NAMESPACES,
  GLOBAL_NAMESPACES,
  ROOT_NAMESPACES,
  areaNamespaces,
  extraAreaNamespaces,
  pickNamespaces,
  type MessageArea,
} from "@/lib/i18n/message-scopes";

// Statische Absicherung gegen MISSING_MESSAGE: Ab jeder page.tsx wird der Import-Graph
// (statische und dynamische Imports, "@/..." und relative Pfade) verfolgt und jeder
// useTranslations("x")/getTranslations("x")-Namespace gesammelt. Jeder davon muss in den
// Namespaces enthalten sein, die auf dieser Route beim Client ankommen (Root-Layout bzw. der
// naechstgelegene <AreaIntlProvider area="...">). Absichtlich grosszuegig: Server-Komponenten
// und nur bedingt gerenderte Teile zaehlen mit.

const FRONTEND_ROOT = path.resolve(__dirname, "..", "..");
const APP_DIR = path.join(FRONTEND_ROOT, "app");
const EXTENSIONS = [".tsx", ".ts", ".jsx", ".js", ".mjs"];
const IMPORT_RE =
  /(?:import|export)\s+(?:type\s+)?(?:[^'"]*?\s+from\s+)?["']([^"']+)["']|import\(\s*["']([^"']+)["']\s*\)/g;
const NAMESPACE_RE =
  /(?:useTranslations|getTranslations)\(\s*(?:\{\s*(?:locale\s*:\s*[^,]+,\s*)?namespace\s*:\s*)?["']([A-Za-z0-9_.]+)["']/g;
const AREA_RE = /<AreaIntlProvider\s+area="([A-Za-z]+)"/;

function resolveImport(fromFile: string, spec: string): string | null {
  let base: string;
  if (spec.startsWith("@/")) {
    base = path.join(FRONTEND_ROOT, spec.slice(2));
  } else if (spec.startsWith(".")) {
    base = path.resolve(path.dirname(fromFile), spec);
  } else {
    return null;
  }
  const candidates = [
    base,
    ...EXTENSIONS.map((ext) => base + ext),
    ...EXTENSIONS.map((ext) => path.join(base, "index" + ext)),
  ];
  return candidates.find((candidate) => fs.existsSync(candidate) && fs.statSync(candidate).isFile()) ?? null;
}

const fileCache = new Map<string, { imports: string[]; namespaces: string[] }>();
function fileInfo(file: string) {
  const cached = fileCache.get(file);
  if (cached) return cached;
  const source = fs.readFileSync(file, "utf-8");
  const imports: string[] = [];
  for (const match of source.matchAll(IMPORT_RE)) {
    const resolved = resolveImport(file, match[1] ?? match[2]);
    if (resolved && !/\.(test|spec)\./.test(resolved)) imports.push(resolved);
  }
  const namespaces = Array.from(source.matchAll(NAMESPACE_RE), (match) => match[1].split(".")[0]);
  const info = { imports, namespaces };
  fileCache.set(file, info);
  return info;
}

// Namespace -> erste Datei, die ihn verwendet (fuer verstaendliche Fehlermeldungen).
function usedNamespaces(entries: string[]): Map<string, string> {
  const seen = new Set<string>();
  const stack = [...entries];
  const result = new Map<string, string>();
  while (stack.length > 0) {
    const file = stack.pop()!;
    if (seen.has(file)) continue;
    seen.add(file);
    const info = fileInfo(file);
    for (const namespace of info.namespaces) {
      if (!result.has(namespace)) result.set(namespace, path.relative(FRONTEND_ROOT, file));
    }
    stack.push(...info.imports);
  }
  return result;
}

function findPages(dir: string): string[] {
  const pages: string[] = [];
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) pages.push(...findPages(full));
    else if (entry.name === "page.tsx") pages.push(full);
  }
  return pages;
}

function areaOf(file: string): MessageArea | null {
  if (!fs.existsSync(file)) return null;
  const match = AREA_RE.exec(fs.readFileSync(file, "utf-8"));
  return match ? (match[1] as MessageArea) : null;
}

// Was auf der Route einer page.tsx beim Client ankommt, plus die Dateien, die unter diesem
// Provider rendern (Seite und Layouts zwischen Provider und Seite).
function routeScope(page: string): { provided: readonly string[]; entries: string[]; label: string } {
  const entries = [page];
  const pageArea = areaOf(page);
  if (pageArea) {
    return { provided: extraAreaNamespaces(pageArea) ?? ROOT_NAMESPACES, entries, label: pageArea };
  }
  let dir = path.dirname(page);
  while (dir !== APP_DIR) {
    const layout = path.join(dir, "layout.tsx");
    if (fs.existsSync(layout)) {
      entries.push(layout);
      const area = areaOf(layout);
      if (area) {
        return { provided: extraAreaNamespaces(area) ?? ROOT_NAMESPACES, entries, label: area };
      }
    }
    dir = path.dirname(dir);
  }
  return { provided: ROOT_NAMESPACES, entries, label: "root" };
}

const pages = findPages(APP_DIR).sort();

describe("message-scopes", () => {
  it("kennt nur Namespaces, die als Katalogdatei existieren", () => {
    const catalog = new Set(
      fs
        .readdirSync(path.join(FRONTEND_ROOT, "messages", defaultLocale))
        .filter((name) => name.endsWith(".json"))
        .map((name) => name.slice(0, -".json".length))
    );
    const all = [...GLOBAL_NAMESPACES, ...Object.values(AREA_NAMESPACES).flat()];
    expect(all.filter((namespace) => !catalog.has(namespace))).toEqual([]);
  });

  it("Root-Layout und globale Fehlerseite brauchen nur globale Namespaces", () => {
    const used = usedNamespaces([path.join(APP_DIR, "layout.tsx"), path.join(APP_DIR, "error.tsx")]);
    const missing = [...used].filter(([namespace]) => !(GLOBAL_NAMESPACES as readonly string[]).includes(namespace));
    expect(missing).toEqual([]);
  });

  it.each(pages.map((page) => [path.relative(FRONTEND_ROOT, page), page]))(
    "%s bekommt alle verwendeten Namespaces",
    (_label, page) => {
      const scope = routeScope(page);
      const used = usedNamespaces(scope.entries);
      const missing = [...used]
        .filter(([namespace]) => !scope.provided.includes(namespace))
        .map(([namespace, file]) => `${namespace} (Bereich ${scope.label}, z.B. ${file})`);
      expect(missing).toEqual([]);
    }
  );

  // Die Protokoll-Routen haben (noch) kein eigenes layout.tsx; sobald es mit
  // <AreaIntlProvider area="protocols"> angelegt wird, muss der Bereich alles abdecken.
  it("Bereich protocols deckt alle Protokoll-Routen ab", () => {
    for (const page of pages.filter((file) => file.startsWith(path.join(APP_DIR, "protocols") + path.sep))) {
      const used = usedNamespaces([page]);
      const missing = [...used.keys()].filter((namespace) => !areaNamespaces("protocols").includes(namespace));
      expect(missing, path.relative(FRONTEND_ROOT, page)).toEqual([]);
    }
  });

  it("pickNamespaces waehlt nur vorhandene Top-Level-Namespaces", () => {
    expect(pickNamespaces({ a: { x: 1 }, b: { y: 2 } }, ["a", "c"])).toEqual({ a: { x: 1 } });
  });
});
