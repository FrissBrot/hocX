export type SaveState = "saving" | "saved" | "error";

export type TemplateSummary = {
  id: number;
  tenant_id?: number;
  name: string;
  description?: string | null;
  version: number;
  status: string;
  document_template_id?: number | null;
  created_by?: number | null;
  created_at?: string;
  updated_at?: string;
};

export type ProtocolSummary = {
  id: number;
  tenant_id?: number;
  template_id?: number;
  template_version?: number;
  protocol_number: string;
  title: string | null;
  protocol_date?: string;
  event_id?: number | null;
  status: string;
  created_by?: number | null;
  created_at?: string;
  updated_at?: string;
};

export type ElementDefinition = {
  id: number;
  tenant_id: number;
  element_type_id: number;
  render_type_id: number;
  title: string;
  display_title: string | null;
  description: string | null;
  is_editable: boolean;
  allows_multiple_values: boolean;
  export_visible: boolean;
  latex_template: string | null;
  configuration_json: Record<string, unknown>;
  is_active: boolean;
  created_at: string;
  updated_at: string;
};

export type TemplateElement = {
  id: number;
  template_id: number;
  element_definition_id: number;
  sort_index: number;
  render_order: number | null;
  section_name: string | null;
  section_order: number | null;
  is_required: boolean;
  is_visible: boolean;
  export_visible: boolean;
  heading_text: string | null;
  configuration_override_json: Record<string, unknown>;
  created_at: string;
};
