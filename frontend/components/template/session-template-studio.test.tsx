import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { fetchMock, toast } = vi.hoisted(() => ({ fetchMock: vi.fn(), toast: vi.fn() }));
vi.mock("@/lib/api/client", () => ({ browserApiFetch: fetchMock }));
vi.mock("@/contexts/confirm-context", () => ({ useConfirm: () => vi.fn(async () => true) }));
vi.mock("@/contexts/toast-context", () => ({ useToast: () => toast }));

import type { TemplateElement } from "@/types/api";

import { SessionTemplateWorkspace } from "./session-template-studio";

function element(overrides: Partial<TemplateElement> = {}): TemplateElement {
  return {
    id: "te-1",
    template_id: "tpl",
    element_definition_id: "def-1",
    sort_index: 10,
    title: "Begrüssung",
    description: null,
    configuration_json: {},
    created_at: "",
    behavior: { is_editable: true, is_visible: true, export_visible: true, copy_from_last_protocol: false, title_as_subtitle: true },
    definition_is_library: true,
    definition_usage_count: 2,
    blocks: [
      {
        id: 1,
        template_element_id: "te-1",
        element_definition_block_id: 1,
        title: "Notiz",
        description: null,
        block_title: null,
        default_content: null,
        copy_from_last_protocol: false,
        element_type_id: 1,
        render_type_id: 2,
        is_editable: true,
        allows_multiple_values: false,
        export_visible: false,
        is_visible: true,
        title_as_subtitle: true,
        behavior_defaults: { is_editable: true, is_visible: true, export_visible: true, copy_from_last_protocol: false, title_as_subtitle: true },
        sort_index: 10,
        render_order: 10,
        configuration_json: {},
        created_at: "",
      },
    ],
    ...overrides,
  } as TemplateElement;
}

const data = { participants: [], events: [], lists: [], listEntries: {}, ensureListEntries: () => undefined, knownEventTags: [], tagConfig: {}, accounts: [], cycleConfigs: [] } as never;

const onReorder = vi.fn(async () => true);
const onOpenResponsibility = vi.fn();

function renderWorkspace(elements: TemplateElement[], onElementsChange = vi.fn()) {
  render(
    <SessionTemplateWorkspace
      templateId="tpl"
      elements={elements}
      onElementsChange={onElementsChange}
      onReorder={onReorder}
      onOpenResponsibility={onOpenResponsibility}
      responsibleFor={(item) => (item.id === "te-1" ? [{ id: "p1", name: "Anna Keller", initials: "AK" }] : [])}
      blockEditorData={data}
      cycleConfigs={[]}
    />
  );
  return onElementsChange;
}

describe("SessionTemplateWorkspace", () => {
  beforeEach(() => {
    fetchMock.mockReset();
    toast.mockReset();
    onReorder.mockClear();
    onOpenResponsibility.mockClear();
    fetchMock.mockImplementation(async (url: string) => (url.startsWith("/api/element-definitions?library") ? [] : element()));
  });

  it("shows where a building block appears and switches it per template", async () => {
    renderWorkspace([element()]);
    expect(screen.getByText("Nicht im PDF")).toBeInTheDocument();
    expect(screen.getByText("In 2 Traktanden verwendet")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Notiz/ }));
    fireEvent.click(screen.getByLabelText(/Im PDF zeigen/));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith("/api/template-elements/te-1/behavior", expect.objectContaining({ method: "PATCH" })));
    const call = fetchMock.mock.calls.find(([url]) => url === "/api/template-elements/te-1/behavior");
    expect(JSON.parse(call![1].body)).toEqual({ scope: "block", block_id: 1, export_visible: true });
  });

  it("asks whether a content change of a shared building block applies everywhere", async () => {
    renderWorkspace([element()]);
    fireEvent.click(screen.getByRole("button", { name: /^1\s*Begrüssung/ }));
    const title = screen.getByRole("textbox", { name: /^Titel/ });
    fireEvent.change(title, { target: { value: "Willkommen" } });
    fireEvent.blur(title);
    expect(await screen.findByText(/wird in 2 Traktanden verwendet/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Nur in dieser Vorlage" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith("/api/template-elements/te-1/detach", { method: "POST" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith("/api/element-definitions/def-1", expect.objectContaining({ method: "PATCH", body: JSON.stringify({ title: "Willkommen" }) })));
  });

  it("shows the saved blocks next to the agenda items until one is selected", async () => {
    fetchMock.mockImplementation(async (url: string) =>
      url.startsWith("/api/element-definitions?library") ? [{ id: "def-9", title: "Kassabericht", usage_count: 3, blocks: [{ id: 1, element_type_id: 12 }, { id: 2, element_type_id: 13 }] }] : element()
    );
    renderWorkspace([element(), element({ id: "te-2", sort_index: 20, title: "Varia", definition_usage_count: 1 })]);
    expect(screen.getByText("2 Traktanden · 2 Bausteine")).toBeInTheDocument();
    const panel = screen.getByRole("complementary", { name: "Eigenschaften" });
    expect(await screen.findByRole("button", { name: /Kassabericht/ })).toHaveTextContent("3×");
    expect(panel).toHaveTextContent("Meine Bausteine");
    // «Aus Meine Bausteine einfügen» führt in die Suche
    fireEvent.click(screen.getByRole("button", { name: "Aus «Meine Bausteine» einfügen" }));
    await waitFor(() => expect(screen.getByPlaceholderText("Bausteine suchen")).toHaveFocus());
  });

  it("shows the responsible people and moves agenda items from the card", async () => {
    renderWorkspace([element(), element({ id: "te-2", sort_index: 20, title: "Varia", definition_usage_count: 1 })]);
    expect(screen.getByLabelText("Verantwortlich: Anna Keller")).toHaveTextContent("AK");
    fireEvent.click(screen.getByRole("button", { name: "«Varia» nach oben" }));
    await waitFor(() => expect(onReorder).toHaveBeenCalled());
    expect((onReorder.mock.calls[0] as unknown as [TemplateElement[]])[0].map((item) => item.id)).toEqual(["te-2", "te-1"]);
    expect(screen.getByRole("button", { name: "«Begrüssung» nach oben" })).toBeDisabled();

    fireEvent.click(screen.getByRole("button", { name: /^1\s*Begrüssung/ }));
    const panel = screen.getByRole("complementary", { name: "Eigenschaften" });
    expect(panel).toHaveTextContent("Traktandum 1");
    expect(panel).toHaveTextContent("Anna Keller");
    fireEvent.click(screen.getByRole("button", { name: "Ändern" }));
    expect(onOpenResponsibility).toHaveBeenCalledWith("te-1");
    expect(screen.getByRole("switch", { name: /In Einladung und Traktandenliste zeigen/ })).toBeChecked();
    fireEvent.click(screen.getByRole("button", { name: "Schliessen" }));
    expect(panel).toHaveTextContent("Meine Bausteine");
  });
});

