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

function renderWorkspace(elements: TemplateElement[], onElementsChange = vi.fn()) {
  render(
    <SessionTemplateWorkspace
      templateId="tpl"
      elements={elements}
      onElementsChange={onElementsChange}
      onReorder={vi.fn(async () => true)}
      onOpenResponsibility={vi.fn()}
      responsibilityTitle={(item) => item.title}
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
});
