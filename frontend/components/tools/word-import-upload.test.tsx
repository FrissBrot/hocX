// Dateiauswahl des Word-Imports (Warteschlange und Assistent): per Tastatur erreichbar und in der
// UI-Sprache beschriftet. Gerendert mit den englischen Texten, damit fest deutsche Texte auffallen.
import fs from "node:fs";
import path from "node:path";

import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { WordImportQueueView } from "./word-import-queue-view";
import { WordImportWizard } from "./word-import-wizard";

vi.mock("next-intl", async (importOriginal) => {
  const actual = await importOriginal<typeof import("next-intl")>();
  const dir = path.join(process.cwd(), "messages", "en");
  const messages = Object.fromEntries(
    fs
      .readdirSync(dir)
      .filter((name) => name.endsWith(".json"))
      .map((name) => [name.slice(0, -".json".length), JSON.parse(fs.readFileSync(path.join(dir, name), "utf-8"))])
  );
  return {
    ...actual,
    useTranslations: (namespace?: string) => actual.createTranslator({ locale: "en", messages, namespace }),
    useLocale: () => "en",
  };
});
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn(), refresh: vi.fn(), replace: vi.fn() }) }));
vi.mock("@/contexts/confirm-context", () => ({ useConfirm: () => vi.fn() }));
vi.mock("@/lib/hooks/use-refresh-on-restore", () => ({ useRefreshOnRestore: () => undefined }));
vi.mock("@/lib/hooks/use-event-field-config", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/hooks/use-event-field-config")>()),
  useEventFieldConfig: () => (({}) as never),
}));
vi.mock("@/lib/api/client", async (importOriginal) => ({ ...(await importOriginal<typeof import("@/lib/api/client")>()), browserApiFetch: vi.fn(() => new Promise(() => undefined)) }));
vi.mock("@/lib/api/word-import", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api/word-import")>()),
  ingestWordImportDocuments: vi.fn(() => new Promise(() => undefined)),
  setLastWordImportTemplate: vi.fn(() => Promise.resolve()),
  deleteWordImportDocument: vi.fn(),
}));

const templates = [{ id: "tpl-1", name: "Vorstand", status: "active" }] as never;

describe("Word import file selection", () => {
  let click: ReturnType<typeof vi.spyOn>;
  beforeEach(() => {
    click = vi.spyOn(HTMLInputElement.prototype, "click").mockImplementation(() => undefined);
  });
  afterEach(() => click.mockRestore());

  it("opens the file picker of the queue from the keyboard", () => {
    render(<WordImportQueueView templates={templates} initialDocuments={[]} initialTemplateId={null} />);
    const zone = screen.getByRole("button", { name: /Choose files/ });
    expect(zone.tabIndex).toBe(0);
    fireEvent.keyDown(zone, { key: "Enter" });
    expect(click).toHaveBeenCalledTimes(1);
    fireEvent.keyDown(zone, { key: " " });
    expect(click).toHaveBeenCalledTimes(2);
  });

  it("opens the file picker of the wizard from the keyboard and labels the chosen file in the UI language", () => {
    const { container } = render(<WordImportWizard templates={templates} participants={[]} />);
    const zone = screen.getByRole("button", { name: /Choose file/ });
    expect(zone.tabIndex).toBe(0);
    fireEvent.keyDown(zone, { key: "Enter" });
    expect(click).toHaveBeenCalledTimes(1);

    const input = container.querySelector<HTMLInputElement>('input[type="file"]')!;
    const file = new File([new Uint8Array(1024 * 1024)], "hock.docx");
    fireEvent.change(input, { target: { files: [file] } });
    expect(screen.getByText("hock.docx")).toBeInTheDocument();
    expect(zone.textContent).not.toMatch(/zum Ersetzen|hierher ziehen/);
    expect(zone.textContent).toContain("1.0 MB");
  });
});
