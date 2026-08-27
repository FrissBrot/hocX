export type SaveState = "saving" | "saved" | "error";

export type MfaFactorType = "totp" | "webauthn";

export type SessionInfo = {
  authenticated: boolean;
  user: {
    id: string;
    first_name: string;
    last_name: string;
    display_name: string;
    email: string;
    preferred_language: string;
    protocol_accordion_enabled: boolean;
    default_tenant_id: string | null;
  } | null;
  current_tenant: TenantSummary | null;
  current_role: string | null;
  available_tenants: TenantMembership[];
  bridge_redirect_url: string | null;
};

export type PendingMfaMethod = {
  factor_type: MfaFactorType;
  label: string;
};

export type PendingMfaLogin = {
  status: "setup_required" | "verification_required";
  ticket: string;
  required: boolean;
  user_display_name: string;
  user_email: string;
  tenant_name: string | null;
  available_methods: PendingMfaMethod[];
  default_factor_type: MfaFactorType | null;
  default_factor_label: string | null;
  can_add_totp: boolean;
  can_add_passkey: boolean;
};

export type LoginResponse = SessionInfo & {
  mfa: PendingMfaLogin | null;
};

export type MfaFactor = {
  id: string;
  factor_type: MfaFactorType;
  label: string;
  created_at: string;
  last_used_at: string | null;
};

export type UserMfaOverview = {
  required: boolean;
  has_factors: boolean;
  can_add_passkey_here: boolean;
  preferred_factor_type: MfaFactorType | null;
  preferred_factor_label: string | null;
  factors: MfaFactor[];
};

export type TotpEnrollmentStart = {
  flow_token: string;
  secret: string;
  manual_entry_key: string;
  provisioning_uri: string;
  issuer: string;
  account_name: string;
};

export type PasskeyRegistrationStart = {
  flow_token: string;
  public_key: Record<string, unknown>;
};

export type PasskeyAssertionStart = {
  flow_token: string;
  public_key: Record<string, unknown>;
};

export type TenantSummary = {
  id: string;
  name: string;
  profile_image_path: string | null;
  profile_image_url: string | null;
  public_slug: string | null;
  created_at?: string | null;
  updated_at?: string | null;
};

export type TenantDomainPurpose = "app" | "abgabebox";

export type TenantDomain = {
  id: string;
  purpose: TenantDomainPurpose;
  domain: string;
  status: "pending" | "active";
  verification_token: string;
  challenge_record_name: string;
  target_host: string | null;
  verified_at: string | null;
  is_healthy: boolean;
  last_checked_at: string | null;
};

export type SubmissionSourceType = "events" | "list";
export type SubmissionElementStatus = "open" | "submitted" | "closed";
export type SubmissionSortOrder = "alphabetical" | "date" | "proximity";

export type SubmissionAssignment = {
  id: string;
  tenant_id: string;
  title: string;
  description: string | null;
  public_slug: string;
  source_type: SubmissionSourceType;
  tag_filter: string | null;
  offset_days_before: number | null;
  offset_days_after: number | null;
  list_definition_id: string | null;
  deadline: string | null;
  allowed_file_types: string[];
  max_files_per_element: number | null;
  max_file_size_mb: number;
  sort_order: SubmissionSortOrder;
  responsible_participant_source: string | null;
  created_at: string;
  updated_at: string;
};

export type AssignmentSummary = {
  submitted: number;
  quarantine: number;
  infected: number;
  total: number | null;
};

export type SubmissionFile = {
  id: string;
  original_name: string;
  mime_type: string | null;
  file_size_bytes: number | null;
  content_url: string;
  scan_status: string;
};

export type SubmissionUploadLogEntry = {
  id: string;
  element_ref: string;
  status: string;
  error_message: string | null;
  created_at: string;
};

export type SubmissionElementStatusEntry = {
  element_ref: string;
  label: string;
  window_start: string | null;
  window_end: string | null;
  status: SubmissionElementStatus;
  submitted_at: string | null;
  upload_id: string | null;
  files: SubmissionFile[];
  responsible_participant_id: string | null;
};

export type PlatformOidcConfigPublic = { enabled: boolean; issuer_url: string };
export type PlatformOidcConfigRead = { enabled: boolean; issuer_url: string; client_id: string; scopes: string };
export type PlatformOidcConfigWrite = { enabled: boolean; issuer_url: string; client_id: string; client_secret: string; scopes: string };

export type TenantMembership = {
  tenant_id: string;
  tenant_name: string;
  tenant_profile_image_path: string | null;
  tenant_profile_image_url: string | null;
  role_code: string;
  is_active: boolean;
};

export type UserSummary = {
  id: string;
  first_name: string;
  last_name: string;
  display_name: string;
  email: string;
  preferred_language: string;
  is_active: boolean;
  external_identity_json: Record<string, unknown>;
  default_tenant_id: string | null;
  memberships: TenantMembership[];
  login_enabled: boolean;
  is_participant_account: boolean;
  created_at: string;
  updated_at: string;
};

export type AdminTenantUser = {
  user_id: string;
  email: string;
  display_name: string;
  role_code: string;
  login_enabled: boolean;
  is_active: boolean;
};

export type AdminSessionInfo = {
  authenticated: boolean;
  admin: { id: string; email: string; display_name: string; role: "owner" | "support" } | null;
};

export type AdminTenantSummary = {
  id: string;
  name: string;
  profile_image_path: string | null;
  profile_image_url: string | null;
  public_slug: string | null;
  participant_count: number;
  user_count: number;
  created_at: string;
};

export type AdminTenantPage = {
  items: AdminTenantSummary[];
  total: number;
};

export type TenantCleanupCategory = "protocols" | "list_entries" | "lists_full" | "events" | "todos" | "participants" | "documents";

export type TenantCleanupCounts = {
  protocols: number;
  list_entries: number;
  lists_full: number;
  events: number;
  todos: number;
  participants: number;
  documents: number;
};

export type AdminDomainSummary = {
  id: string;
  tenant_id: string;
  tenant_name: string;
  purpose: TenantDomainPurpose;
  domain: string;
  status: "pending" | "active";
  is_healthy: boolean;
  last_checked_at: string | null;
  verified_at: string | null;
  created_at: string;
};

export type AdminDomainPage = {
  items: AdminDomainSummary[];
  total: number;
};

export type AdminUserPage = {
  items: UserSummary[];
  total: number;
};

export type SystemErrorLogEntry = {
  id: string;
  source: string;
  tenant_id: string | null;
  tenant_name: string | null;
  actor_email: string | null;
  request_method: string | null;
  request_path: string | null;
  status_code: number | null;
  error_type: string;
  error_message: string;
  traceback: string | null;
  created_at: string;
};

export type SystemErrorLogPage = {
  items: SystemErrorLogEntry[];
  total: number;
};

export type SystemErrorLogFilterOptions = {
  error_types: string[];
  sources: string[];
};

export type PlatformAdminSummary = {
  id: string;
  email: string;
  display_name: string;
  is_active: boolean;
  role: "owner" | "support";
  created_at: string;
  updated_at: string;
};

export type TemplateSummary = {
  id: string;
  tenant_id?: string;
  name: string;
  description?: string | null;
  next_event_id?: string | null;
  last_event_id?: string | null;
  todo_due_event_tag?: string | null;
  protocol_number_pattern?: string | null;
  title_pattern?: string | null;
  auto_create_next_protocol?: boolean;
  cycle_config_id?: string | null;
  cycle_config?: CycleConfigSummary | null;
  version: number;
  status: string;
  document_template_id?: string | null;
  created_by?: string | null;
  created_at?: string;
  updated_at?: string;
};

export type CycleConfigSummary = {
  id: string;
  tenant_id: string;
  name: string;
  reset_month: number;
  reset_day: number;
  name_pattern?: string | null;
  created_at?: string;
  updated_at?: string;
};

export type CycleAssignment = {
  cycle_config_id: string;
  cycle_year: number;
};

export type CycleInfo = {
  cycle_year: number;
  name: string;
};

export type ParticipantSummary = {
  id: string;
  tenant_id: string;
  app_user_id?: string | null;
  first_name: string | null;
  last_name: string | null;
  display_name: string;
  email: string | null;
  is_active: boolean;
  joined_at: string | null;
  left_at: string | null;
  exclude_from_attendance?: boolean;
  created_at: string;
  updated_at: string;
};

export type EventSummary = {
  id: string;
  tenant_id: string;
  event_date: string;
  event_end_date: string | null;
  // Lookup-table code, deliberately kept as a small numeric id - not migrated to public_id.
  event_category_id: number;
  tag: string | null;
  title: string;
  description: string | null;
  participant_count: number;
  is_cancelled: boolean;
  organizer_ids: string[] | null;
  leadership_ids: string[] | null;
  participant_ids: string[] | null;
  spezial1_ids: string[] | null;
  spezial2_ids: string[] | null;
  spezial3_ids: string[] | null;
  location: string | null;
  spezial_text1: string | null;
  spezial_text2: string | null;
  spezial_text3: string | null;
  cycle_assignments: CycleAssignment[];
  created_at: string;
  updated_at: string;
};

export type EventImportPreviewRow = {
  row_number: number;
  event_date: string | null;
  event_end_date: string | null;
  tag: string | null;
  title: string | null;
  description: string | null;
  participant_count: number | null;
  error: string | null;
};

export type EventImportPreview = {
  detected_columns: string[];
  resolved_map: Record<string, string>;
  rows: EventImportPreviewRow[];
  valid_count: number;
  error_count: number;
};

export type StructuredListValueType = "text" | "participant" | "participants" | "event";

export type StructuredListDefinition = {
  id: string;
  tenant_id: string;
  name: string;
  description: string | null;
  column_one_title: string;
  column_one_value_type: StructuredListValueType;
  column_two_title: string;
  column_two_value_type: StructuredListValueType;
  is_active: boolean;
  content_version: number;
  created_at: string;
  updated_at: string;
};

export type ListSnapshot = {
  synced_version: number;
  column_one_title: string;
  column_one_value_type: StructuredListValueType;
  column_two_title: string;
  column_two_value_type: StructuredListValueType;
  previous: ListSnapshot | null;
};

export type TrackedListValues = { column_one_value: Record<string, unknown>; column_two_value: Record<string, unknown> };

export type WholeListSnapshot = ListSnapshot & {
  entries: {
    id: string;
    sort_index: number;
    column_one_value: Record<string, unknown>;
    column_two_value: Record<string, unknown>;
    _tracked?: "added" | "changed" | "removed";
    _tracked_before?: TrackedListValues;
  }[];
};

export type RowListSnapshot =
  | { synced_version: number; entry_exists: false; _tracked?: undefined; _tracked_before?: undefined }
  | (ListSnapshot & {
      entry_exists: true;
      column_one_value: Record<string, unknown>;
      column_two_value: Record<string, unknown>;
      _tracked?: "changed" | "removed";
      _tracked_before?: TrackedListValues;
    });

export type StructuredListEntry = {
  id: string;
  list_definition_id: string;
  sort_index: number;
  column_one_value: Record<string, unknown>;
  column_two_value: Record<string, unknown>;
  created_at: string;
  updated_at: string;
};

export type ProtocolSummary = {
  id: string;
  tenant_id?: string;
  template_id?: string;
  template_version?: number;
  document_template_id?: string | null;
  document_template_version?: number | null;
  protocol_number: string;
  title: string | null;
  protocol_date?: string;
  event_id?: string | null;
  status: string;
  version_major?: number;
  version_minor?: number;
  version_final_minor?: number;
  session_notes?: string | null;
  track_changes_enabled?: boolean;
  created_by?: string | null;
  created_at?: string;
  updated_at?: string;
  latest_pdf_url?: string | null;
  import_source_filename?: string | null;
  import_source_url?: string | null;
};

export type NextSessionAttendanceEntry = {
  participant_id: string;
  participant_name: string;
  status: string;
};

export type NextSessionInfo = {
  protocol: ProtocolSummary | null;
  attendance_block_id: string | null;
  entries: NextSessionAttendanceEntry[];
};

export type DocumentTemplatePart = {
  id: string;
  tenant_id: string;
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
  id: string;
  tenant_id: string;
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
  // Client-owned opaque id living inside ElementDefinition.configuration_json["blocks"][].id -
  // not a database row/FK, deliberately left as plain number (unaffected by the public_id migration).
  id: number;
  title: string;
  description: string | null;
  block_title: string | null;
  default_content: string | null;
  copy_from_last_protocol?: boolean;
  // Lookup-table codes, deliberately kept as small numeric ids.
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
  id: string;
  tenant_id: string;
  title: string;
  description: string | null;
  is_active: boolean;
  blocks: ElementDefinitionBlock[];
  created_at: string;
  updated_at: string;
};

export type TemplateElementBlock = {
  // Client-owned opaque ids (see ElementDefinitionBlock.id) - deliberately left as plain number.
  id: number;
  template_element_id: string;
  element_definition_block_id: number | null;
  title: string;
  description: string | null;
  block_title: string | null;
  default_content: string | null;
  copy_from_last_protocol: boolean;
  // Lookup-table codes, deliberately kept as small numeric ids.
  element_type_id: number;
  render_type_id: number;
  is_editable: boolean;
  allows_multiple_values: boolean;
  export_visible: boolean;
  is_visible: boolean;
  title_as_subtitle: boolean;
  sort_index: number;
  render_order: number | null;
  latex_template: string | null;
  configuration_json: Record<string, unknown>;
  created_at: string;
};

export type TemplateElementBehaviorField = "is_editable" | "is_visible" | "export_visible" | "copy_from_last_protocol" | "title_as_subtitle";

export type TemplateElement = {
  id: string;
  template_id: string;
  element_definition_id: string;
  sort_index: number;
  title: string;
  description: string | null;
  configuration_json: Record<string, unknown>;
  created_at: string;
  blocks: TemplateElementBlock[];
  behavior: Record<TemplateElementBehaviorField, boolean>;
};

export type ProtocolTodo = {
  id: string;
  protocol_element_block_id: string;
  sort_index: number;
  task: string;
  assigned_user_id: string | null;
  assigned_participant_id: string | null;
  assigned_participant_name: string | null;
  // Lookup-table code, deliberately kept as a small numeric id.
  todo_status_id: number;
  todo_status_code: string | null;
  due_date: string | null;
  due_event_id: string | null;
  due_event_title?: string | null;
  due_event_date?: string | null;
  due_marker?: string | null;
  resolved_due_date?: string | null;
  resolved_due_label?: string | null;
  completed_at: string | null;
  reference_link: string | null;
  tags: string[];
  created_by: string | null;
  created_at: string;
  updated_at: string;
  closed_in_protocol_id: string | null;
  tracked_change?: "added" | "changed" | null;
  tracked_change_before_json?: { task?: string; tags?: string[] } | null;
  pending_delete?: boolean;
};

export type TodoListItem = ProtocolTodo & {
  protocol_id: string | null;
  protocol_number: string | null;
  protocol_date: string | null;
  protocol_title: string | null;
  protocol_status: string | null;
  block_title: string | null;
  submission_assignment_id: string | null;
  element_ref: string | null;
};

export type TodoBlock = {
  block_id: string;
  block_title: string | null;
  protocol_id: string;
  protocol_number: string;
  protocol_title: string | null;
  protocol_date: string;
};

export type ProtocolImage = {
  id: string;
  protocol_element_block_id: string;
  stored_file_id: string;
  sort_index: number;
  title: string | null;
  caption: string | null;
  original_name: string;
  mime_type: string | null;
  file_size_bytes: number | null;
  content_url: string;
};

export type ProtocolElementBlock = {
  id: string;
  protocol_element_id: string;
  template_element_block_id: string | null;
  element_definition_id: string | null;
  // Lookup-table codes, deliberately kept as small numeric ids.
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
  tracked_dirty?: boolean;
  tracked_baseline_content?: string | null;
};

export type ProtocolElement = {
  id: string;
  protocol_id: string;
  template_element_id: string | null;
  sort_index: number;
  section_name_snapshot: string;
  section_order_snapshot: number | null;
  is_required_snapshot: boolean;
  is_visible_snapshot: boolean;
  export_visible_snapshot: boolean;
  show_when_empty: boolean;
  blocks: ProtocolElementBlock[];
};

export type FinanceAccount = {
  id: string;
  name: string;
  currency_label: string;
  description: string | null;
  balance: number;
  provisional_balance: number;
  transaction_count: number;
  created_at: string;
};

export type AttendanceFine = {
  id: string;
  protocol_id: string;
  participant_id: string | null;
  participant_name_snapshot: string;
  fine_type: "late" | "absent";
  amount: number;
  account_id: string;
  status: "pending" | "collected";
  collected_at: string | null;
  collected_transaction_id: string | null;
  closed_in_protocol_id: string | null;
  collected_by_user_id: string | null;
  collected_by_display_name: string | null;
  can_reopen: boolean;
  created_at: string;
};

export type AttendanceFineListItem = AttendanceFine & {
  protocol_number: string | null;
  protocol_date: string | null;
  currency_label: string | null;
};

export type FinanceTransaction = {
  id: string;
  account_id: string;
  amount: number;
  description: string;
  transaction_date: string;
  protocol_id: string | null;
  created_at: string;
  running_balance: number | null;
};

export type StatisticsOverview = {
  attendance_by_participant: { name: string; present: number; absent: number; excused: number; total: number }[];
  attendance_over_time: { month: string; present: number; absent: number; excused: number; total: number }[];
  todos: { open: number; done: number; total: number };
  fines_by_participant: { name: string; count: number; amount: number }[];
  fines_by_type: { fine_type: string; label: string; count: number; amount: number }[];
  finance_by_month: { month: string; account_id: string; account_name: string; income: number; expenses: number; net: number }[];
  participants_total: number;
  participants_active: number;
  protocols_total: number;
  cycles: { cycle_config_id: string; cycle_config_name: string; cycle_year: number; label: string }[];
  groups_stats: { group_name: string; cycle_config_id: string | null; cycle_year: number | null; session_count: number; session_count_with_participants: number; avg_participants: number }[];
};
