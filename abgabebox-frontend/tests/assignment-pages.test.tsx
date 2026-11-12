// Server-Seiten der Abgabe (Dokumentauswahl, Upload-Seite) ohne DOM gerendert: Direktsprung bei
// nur einem Dokument, Zurück-Link ohne Weiterleitungsschleife, Beschreibung über dem Upload.
import type { ReactNode } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { createTranslator } from "next-intl";
import { beforeEach, describe, expect, it, vi } from "vitest";

import de from "@/messages/de/abgabebox.json";

const api = vi.hoisted(() => ({
  getAssignmentDetail: vi.fn(),
  listElements: vi.fn(),
}));

vi.mock("@/lib/api", () => api);

vi.mock("next/navigation", () => ({
  notFound: () => {
    throw new Error("NEXT_NOT_FOUND");
  },
  redirect: (url: string, type?: string) => {
    throw new Error(`NEXT_REDIRECT ${type ?? ""} ${url}`);
  },
  RedirectType: { push: "push", replace: "replace" },
}));

vi.mock("next-intl/server", () => ({
  getTranslations: async (namespace: string) =>
    createTranslator({ locale: "de", messages: { abgabebox: de }, namespace: namespace as never }),
}));

vi.mock("next/link", () => ({
  default: ({ href, children, className }: { href: string; children: ReactNode; className?: string }) => (
    <a href={href} className={className}>{children}</a>
  ),
}));

// Das Formular selbst ist ein Client-Baustein mit eigenen Effekten - hier zählt nur, was die Seite übergibt.
vi.mock("@/components/upload-form", () => ({
  UploadForm: ({ singleElement }: { singleElement?: boolean }) => <div data-testid="upload-form" data-single={String(Boolean(singleElement))} />,
}));

import AssignmentElementsPage from "@/app/[linkToken]/[assignmentSlug]/page";
import ElementUploadPage from "@/app/[linkToken]/[assignmentSlug]/[elementRef]/page";

const assignment = {
  public_slug: "jahresbericht",
  title: "Jahresbericht",
  description: "Bitte den unterschriebenen Bericht als PDF.",
  allowed_file_types: ["pdf"],
  max_files_per_element: 1,
  max_file_size_mb: 20,
  tenant_name: "Testverein",
  privacy_notice_url: null,
};

function element(ref: string, label: string) {
  return { element_ref: ref, label, window_start: null, window_end: null, uploaded_count: 0 };
}

const listParams = { params: Promise.resolve({ linkToken: "tok", assignmentSlug: "jahresbericht" }) };

beforeEach(() => {
  api.getAssignmentDetail.mockReset().mockResolvedValue(assignment);
  api.listElements.mockReset();
});

describe("Dokumentauswahl", () => {
  it("leitet bei nur einem offenen Dokument direkt (replace) zum Upload weiter", async () => {
    api.listElements.mockResolvedValue([element("el-1", "Bericht")]);
    await expect(AssignmentElementsPage(listParams)).rejects.toThrow("NEXT_REDIRECT replace /tok/jahresbericht/el-1");
  });

  it("zeigt bei mehreren Dokumenten die Liste samt Beschreibung", async () => {
    api.listElements.mockResolvedValue([element("el-1", "Bericht"), element("el-2", "Beilage")]);
    const html = renderToStaticMarkup(await AssignmentElementsPage(listParams));
    expect(html).toContain('href="/tok/jahresbericht/el-1"');
    expect(html).toContain('href="/tok/jahresbericht/el-2"');
    expect(html).toContain(assignment.description);
  });

  it("zeigt bei keinem offenen Dokument den Leerzustand statt weiterzuleiten", async () => {
    api.listElements.mockResolvedValue([]);
    const html = renderToStaticMarkup(await AssignmentElementsPage(listParams));
    expect(html).toContain(de.elements.empty);
  });
});

describe("Upload-Seite", () => {
  const params = (ref: string) => ({ params: Promise.resolve({ linkToken: "tok", assignmentSlug: "jahresbericht", elementRef: ref }) });

  it("zeigt die Beschreibung der Abgabe über dem Upload-Feld", async () => {
    api.listElements.mockResolvedValue([element("el-1", "Bericht"), element("el-2", "Beilage")]);
    const html = renderToStaticMarkup(await ElementUploadPage(params("el-1")));
    const descriptionAt = html.indexOf(assignment.description);
    expect(descriptionAt).toBeGreaterThan(-1);
    expect(descriptionAt).toBeLessThan(html.indexOf('data-testid="upload-form"'));
  });

  it("verlinkt bei mehreren Dokumenten zurück zur Dokumentauswahl", async () => {
    api.listElements.mockResolvedValue([element("el-1", "Bericht"), element("el-2", "Beilage")]);
    const html = renderToStaticMarkup(await ElementUploadPage(params("el-2")));
    expect(html).toContain('href="/tok/jahresbericht"');
    expect(html).toContain('data-single="false"');
  });

  it("verlinkt bei nur einem Dokument zur Abgabenliste, damit Zurück nicht in die Weiterleitung führt", async () => {
    api.listElements.mockResolvedValue([element("el-1", "Bericht")]);
    const html = renderToStaticMarkup(await ElementUploadPage(params("el-1")));
    expect(html).toContain('href="/tok"');
    expect(html).not.toContain('href="/tok/jahresbericht"');
    expect(html).toContain(de.elements.backToAssignments);
    expect(html).toContain('data-single="true"');
  });

  it("lässt die Beschreibung weg, wenn die Abgabe keine hat", async () => {
    api.getAssignmentDetail.mockResolvedValue({ ...assignment, description: null });
    api.listElements.mockResolvedValue([element("el-1", "Bericht")]);
    const html = renderToStaticMarkup(await ElementUploadPage(params("el-1")));
    expect(html).not.toContain("box-step-desc");
  });

  it("liefert 404 für ein unbekanntes Dokument", async () => {
    api.listElements.mockResolvedValue([element("el-1", "Bericht")]);
    await expect(ElementUploadPage(params("gibt-es-nicht"))).rejects.toThrow("NEXT_NOT_FOUND");
  });
});
