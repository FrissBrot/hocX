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

export type ProtocolElement = {
  id: number;
  protocol_id: number;
  template_element_id: number | null;
  element_definition_id: number | null;
  element_type_id: number;
  render_type_id: number;
  element_type_code: string | null;
  render_type_code: string | null;
  title_snapshot: string;
  display_title_snapshot: string | null;
  description_snapshot: string | null;
  is_editable_snapshot: boolean;
  allows_multiple_values_snapshot: boolean;
  sort_index: number;
  render_order: number | null;
  section_name_snapshot: string | null;
  section_order_snapshot: number | null;
  is_required_snapshot: boolean;
  is_visible_snapshot: boolean;
  export_visible_snapshot: boolean;
  heading_text_snapshot: string | null;
  latex_template_snapshot: string | null;
  configuration_snapshot_json: Record<string, unknown>;
  text_content: string | null;
  display_compiled_text: string | null;
  display_snapshot_json: Record<string, unknown> | null;
};

export type ProtocolTodo = {
  id: number;
  protocol_element_id: number;
  sort_index: number;
  task: string;
  assigned_user_id: number | null;
  todo_status_id: number;
  todo_status_code: string | null;
  due_date: string | null;
  completed_at: string | null;
  reference_link: string | null;
  created_by: number | null;
  created_at: string;
  updated_at: string;
};

export type ProtocolImage = {
  id: number;
  protocol_element_id: number;
  stored_file_id: number;
  sort_index: number;
  title: string | null;
  caption: string | null;
  original_name: string;
  mime_type: string | null;
  file_size_bytes: number | null;
  content_url: string;
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
