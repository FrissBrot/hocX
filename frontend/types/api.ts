export type SaveState = "saving" | "saved" | "error";

export type SessionInfo = {
  authenticated: boolean;
  user: {
    id: number;
    first_name: string;
    last_name: string;
    display_name: string;
    email: string;
    preferred_language: string;
    is_superadmin: boolean;
  } | null;
  current_tenant: TenantSummary | null;
  current_role: string | null;
  available_tenants: TenantMembership[];
};

export type TenantSummary = {
  id: number;
  name: string;
  profile_image_path: string | null;
  profile_image_url: string | null;
  created_at?: string | null;
  updated_at?: string | null;
};

export type TenantMembership = {
  tenant_id: number;
  tenant_name: string;
  tenant_profile_image_path: string | null;
  role_code: string;
  is_active: boolean;
};

export type UserSummary = {
  id: number;
  first_name: string;
  last_name: string;
  display_name: string;
  email: string;
  preferred_language: string;
  is_active: boolean;
  oidc_subject: string | null;
  oidc_issuer: string | null;
  oidc_email: string | null;
  external_identity_json: Record<string, unknown>;
  default_tenant_id: number | null;
  memberships: TenantMembership[];
  is_superadmin: boolean;
  login_enabled: boolean;
  is_participant_account: boolean;
  created_at: string;
  updated_at: string;
};

export type TemplateSummary = {
  id: number;
  tenant_id?: number;
  name: string;
  description?: string | null;
  next_event_id?: number | null;
  last_event_id?: number | null;
  protocol_number_pattern?: string | null;
  title_pattern?: string | null;
  auto_create_next_protocol?: boolean;
  cycle_reset_month?: number;
  cycle_reset_day?: number;
  version: number;
  status: string;
  document_template_id?: number | null;
  created_by?: number | null;
  created_at?: string;
  updated_at?: string;
};

export type ParticipantSummary = {
  id: number;
  tenant_id: number;
  app_user_id?: number | null;
  first_name: string | null;
  last_name: string | null;
  display_name: string;
  email: string | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
};

export type EventSummary = {
  id: number;
  tenant_id: number;
  event_date: string;
  event_end_date: string | null;
  event_category_id: number;
  tag: string | null;
  title: string;
  description: string | null;
  participant_count: number;
  created_at: string;
  updated_at: string;
};

export type StructuredListValueType = "text" | "participant" | "participants" | "event";

export type StructuredListDefinition = {
  id: number;
  tenant_id: number;
  name: string;
  description: string | null;
  column_one_title: string;
  column_one_value_type: StructuredListValueType;
  column_two_title: string;
  column_two_value_type: StructuredListValueType;
  is_active: boolean;
  created_at: string;
  updated_at: string;
};

export type StructuredListEntry = {
  id: number;
  list_definition_id: number;
  sort_index: number;
  column_one_value: Record<string, unknown>;
  column_two_value: Record<string, unknown>;
  created_at: string;
  updated_at: string;
};

export type ProtocolSummary = {
  id: number;
  tenant_id?: number;
  template_id?: number;
  template_version?: number;
  document_template_id?: number | null;
  document_template_version?: number | null;
  protocol_number: string;
  title: string | null;
  protocol_date?: string;
  event_id?: number | null;
  status: string;
  created_by?: number | null;
  created_at?: string;
  updated_at?: string;
};

export type DocumentTemplatePart = {
  id: number;
  tenant_id: number;
  code: string;
  name: string;
  part_type: string;
  description: string | null;
  storage_path: string;
  version: number;
  is_active: boolean;
  created_at: string;
  updated_at: string;
};

export type DocumentTemplate = {
  id: number;
  tenant_id: number;
  code: string;
  name: string;
  description: string | null;
  filesystem_path: string;
  version: number;
  is_active: boolean;
  is_default: boolean;
  configuration_json: Record<string, unknown>;
  created_at: string;
  updated_at: string;
};

export type ElementDefinitionBlock = {
  id: number;
  title: string;
  description: string | null;
  block_title: string | null;
  default_content: string | null;
  copy_from_last_protocol?: boolean;
  element_type_id: number;
  render_type_id: number;
  is_editable: boolean;
  allows_multiple_values: boolean;
  export_visible: boolean;
  is_visible: boolean;
  sort_index: number;
  render_order: number | null;
  latex_template: string | null;
  configuration_json: Record<string, unknown>;
};

export type ElementDefinition = {
  id: number;
  tenant_id: number;
  title: string;
  description: string | null;
  is_active: boolean;
  blocks: ElementDefinitionBlock[];
  created_at: string;
  updated_at: string;
};

export type TemplateElementBlock = {
  id: number;
  template_element_id: number;
  element_definition_block_id: number | null;
  title: string;
  description: string | null;
  block_title: string | null;
  default_content: string | null;
  copy_from_last_protocol?: boolean;
  element_type_id: number;
  render_type_id: number;
  is_editable: boolean;
  allows_multiple_values: boolean;
  export_visible: boolean;
  is_visible: boolean;
  sort_index: number;
  render_order: number | null;
  latex_template: string | null;
  configuration_json: Record<string, unknown>;
  created_at: string;
};

export type TemplateElement = {
  id: number;
  template_id: number;
  element_definition_id: number;
  sort_index: number;
  title: string;
  description: string | null;
  configuration_json: Record<string, unknown>;
  created_at: string;
  blocks: TemplateElementBlock[];
};

export type ProtocolTodo = {
  id: number;
  protocol_element_block_id: number;
  sort_index: number;
  task: string;
  assigned_user_id: number | null;
  assigned_participant_id: number | null;
  assigned_participant_name: string | null;
  todo_status_id: number;
  todo_status_code: string | null;
  due_date: string | null;
  due_event_id: number | null;
  due_event_title?: string | null;
  due_event_date?: string | null;
  due_marker?: string | null;
  resolved_due_date?: string | null;
  resolved_due_label?: string | null;
  completed_at: string | null;
  reference_link: string | null;
  created_by: number | null;
  created_at: string;
  updated_at: string;
};

export type ProtocolImage = {
  id: number;
  protocol_element_block_id: number;
  stored_file_id: number;
  sort_index: number;
  title: string | null;
  caption: string | null;
  original_name: string;
  mime_type: string | null;
  file_size_bytes: number | null;
  content_url: string;
};

export type ProtocolElementBlock = {
  id: number;
  protocol_element_id: number;
  template_element_block_id: number | null;
  element_definition_id: number | null;
  element_type_id: number;
  render_type_id: number;
  element_type_code: string | null;
  render_type_code: string | null;
  title_snapshot: string;
  display_title_snapshot: string | null;
  description_snapshot: string | null;
  block_title_snapshot: string | null;
  copy_from_last_protocol?: boolean;
  is_editable_snapshot: boolean;
  allows_multiple_values_snapshot: boolean;
  sort_index: number;
  render_order: number | null;
  is_required_snapshot: boolean;
  is_visible_snapshot: boolean;
  export_visible_snapshot: boolean;
  latex_template_snapshot: string | null;
  configuration_snapshot_json: Record<string, unknown>;
  text_content: string | null;
  display_compiled_text: string | null;
  display_snapshot_json: Record<string, unknown> | null;
};

export type ProtocolElement = {
  id: number;
  protocol_id: number;
  template_element_id: number | null;
  sort_index: number;
  section_name_snapshot: string;
  section_order_snapshot: number | null;
  is_required_snapshot: boolean;
  is_visible_snapshot: boolean;
  export_visible_snapshot: boolean;
  blocks: ProtocolElementBlock[];
};
