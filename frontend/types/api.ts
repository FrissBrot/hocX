export type SaveState = "saving" | "saved" | "error";

export type MfaFactorType = "totp" | "webauthn";

export type SessionInfo = {
  authenticated: boolean;
  user: {
    id: string;
    first_name: string | null;
    last_name: string | null;
    display_name: string;
    email: string;
    preferred_language: string;
    protocol_accordion_enabled: boolean;
  } | null;
  current_tenant: TenantSummary | null;
  current_role: string | null;
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
  enabled_features: string[];
};

export type TenantSubscriptionFeature = {
  code: string;
  name: string;
  description: string | null;
  standalone_price_monthly_rp: number | null;
  included_in_plan: boolean;
};

export type TenantSubscription = {
  plan_code: string | null;
  plan_name: string | null;
  billing_cycle: "monthly" | "yearly";
  plan_price_monthly_rp: number | null;
  plan_price_yearly_rp: number | null;
  included_user_limit: number | null;
  included_storage_bytes: number | null;
  user_limit_override: number | null;
  effective_user_limit: number | null;
  user_count: number;
  storage_used_bytes: number;
  storage_quota_bytes: number | null;
  package_storage_bytes: number;
  storage_quota_manual_override: boolean;
  features: TenantSubscriptionFeature[];
  estimated_monthly_cost_rp: number | null;
  estimated_yearly_cost_rp: number | null;
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

export type SubmissionSourceType = "events" | "list" | "manual";
export type SubmissionElementStatus = "open" | "submitted" | "closed";
export type SubmissionSortOrder = "alphabetical" | "date" | "proximity";
/** Wann ein Abgabefeld nach einer Abgabe über die Abgabebox automatisch schliesst. */
export type SubmissionAutoClose = "never" | "first_upload" | "max_files";

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
  cycle_config_id: string | null;
  /** 0 = aktueller Zyklus, -1 = vorheriger usw. Leer, wenn kein Zyklus-Filter gesetzt ist. */
  cycle_offsets: number[];
  list_definition_id: string | null;
  deadline: string | null;
  allowed_file_types: string[];
  max_files_per_element: number | null;
  max_file_size_mb: number;
  sort_order: SubmissionSortOrder;
  auto_close: SubmissionAutoClose;
  responsible_participant_source: string | null;
  link_ids: string[];
  created_at: string;
  updated_at: string;
};

export type SubmissionLink = {
  id: string;
  name: string;
  is_default: boolean;
  token: string;
  url: string;
  assignment_count: number;
  created_at: string;
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

export type FileOverviewSource = "protocol_image" | "word_import" | "submission_upload" | "gallery_upload";

export type PhotoAlbumKind = "manual" | "cycle" | "submission" | "submission_element";

export type FileAlbumRef = {
  id: string;
  name: string;
  kind: PhotoAlbumKind;
  is_best: boolean;
};

export type FileOverviewItem = {
  id: string;
  original_name: string;
  mime_type: string | null;
  file_size_bytes: number | null;
  created_at: string;
  source: FileOverviewSource;
  is_image: boolean;
  content_url: string;
  thumbnail_url: string | null;
  tags_url: string;
  metadata_url: string;
  ref_label: string;
  ref_date: string | null;
  // End date of the linked Termin's range - null for a single-day Termin or when there's
  // no linked Termin. Used with ref_date/group_date to label a multi-day Termin's date
  // sections "Termin, Tag 1", "Termin, Tag 2", ... (see grouping.ts).
  ref_end_date: string | null;
  ref_href: string | null;
  tags: string[];
  origin_tag: string;
  sharpness_score: number | null;
  exposure_score: number | null;
  face_quality_score: number | null;
  // Set once the worker has processed this file, regardless of whether a face was found -
  // face_quality_score alone can't express "analyzed, no face" (both are null then).
  face_analyzed_at: string | null;
  // Original pixel dimensions - lets the Fotos gallery reserve each tile's correct
  // aspect-ratio box before the thumbnail has loaded. Null for non-images and for images
  // uploaded before this field existed whose thumbnail hasn't been regenerated since.
  width: number | null;
  height: number | null;
  // The photo's logical date for the Fotos page's date-group headers.
  group_date: string | null;
  // Short context label for that date group's header (protocol/word-import/submission/
  // event) - null when there's nothing more specific than the plain date.
  context_label: string | null;
  // Live Photo: content URL of the short MP4 played on hover (null for ordinary photos).
  live_video_url: string | null;
  // Every album this file belongs to (only populated on the unscoped GET /files listing).
  albums: FileAlbumRef[];
  // Best-of ("Stern") state: within the album this item was fetched for when scoped by
  // album_id, otherwise "best-of in at least one album" (null if in no album at all).
  is_best: boolean | null;
  // Nur in der Albumansicht des Besitzers: automatisch einsortiert, noch nicht freigegeben.
  share_pending?: boolean;
};

export type AlbumTenantShareStatus = {
  tenant_public_id: string;
  // Nur bei Trust (Mandant hat schon einmal eine Freigabe angenommen), sonst null.
  tenant_name: string | null;
  tenant_profile_image_url: string | null;
  status: "pending" | "accepted" | "declined";
  invited_at: string;
  responded_at: string | null;
};

export type PhotoAlbum = {
  id: string;
  name: string;
  kind: PhotoAlbumKind;
  photo_count: number;
  best_of_count: number;
  cover_thumbnail_urls: string[];
  owner_tenant_name: string | null;
  shared_with: AlbumTenantShareStatus[];
  // Gerade geteilt (Mandant eingeladen/angenommen oder aktiver Album-Link); Partner-Alben immer.
  is_shared: boolean;
  // Nur für den Besitzer: automatisch einsortierte Fotos, die noch freigegeben werden müssen.
  pending_share_count: number;
};

export type AlbumPendingRelease = {
  album_id: string;
  album_name: string;
  album_kind: PhotoAlbumKind;
  pending_count: number;
};

export type SharedTargetAlbum = {
  album_id: string;
  album_name: string;
};

export type AlbumShareRequest = {
  album_id: string;
  album_name: string;
  owner_tenant_name: string;
  created_at: string;
};

// Ohne Trust nur die ID (trusted=false, Rest null); mit Trust Name, Profilbild usw.
export type TenantLookup = {
  id: string;
  trusted: boolean;
  name: string | null;
  slug: string | null;
  participant_count: number | null;
  profile_image_url: string | null;
};

export type ShareLinkStatus = "active" | "expired" | "revoked";

export type ShareLink = {
  id: string;
  name: string;
  url: string;
  album_name: string | null;
  file_count: number;
  created_at: string;
  created_by_name: string | null;
  expires_at: string | null;
  revoked_at: string | null;
  status: ShareLinkStatus;
  share_location: boolean;
  share_capture_date: boolean;
  share_camera: boolean;
};

export type CalendarFeedKind = "events" | "todos";

// Kalender-Abo ("Verknuepfungen"): `path` ist relativ, die eigene Origin kommt im Browser davor.
export type CalendarFeed = {
  kind: CalendarFeedKind;
  calendar_name: string;
  path: string;
  todo_scope: "mine" | "all";
  include_completed: boolean;
  hide_details: boolean;
  created_at: string;
  token_created_at: string;
  last_accessed_at: string | null;
  status: "active" | "invalid";
};

export type PublicShareFile = {
  id: string;
  original_name: string;
  mime_type: string | null;
  file_size_bytes: number | null;
  is_image: boolean;
  width: number | null;
  height: number | null;
  taken_at: string | null;
  thumbnail_url: string | null;
  view_url: string | null;
  download_url: string;
};

export type PublicShare = {
  name: string;
  context: string | null;
  is_album: boolean;
  tenant_name: string;
  expires_at: string | null;
  total_size_bytes: number;
  date_from: string | null;
  date_to: string | null;
  files: PublicShareFile[];
  download_all_url: string | null;
};

export type SimilarityGroup = {
  best_id: string;
  images: FileOverviewItem[];
};

export type PhotoAnalysisProgress = {
  total_images: number;
  analyzed_images: number;
  pending_images: number;
  active_jobs: number;
  active_job_image_count: number;
};

export type FileStats = {
  document_count: number;
  photo_count: number;
  total_bytes: number;
};

export type FileBulkDeleteResult = {
  deleted_ids: string[];
  errors: string[];
};

export type PhotoAnalysisJob = {
  id: string;
  status: "queued" | "running" | "done" | "failed";
  image_count: number;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  error: string | null;
};

export type GalleryUploadJob = {
  id: string;
  status: "queued" | "running" | "done" | "failed";
  // null until a ZIP has been opened and its matching entries counted - see
  // GalleryUploadModal/gallery-upload-progress.tsx.
  total_files: number | null;
  processed_files: number;
  imported_count: number;
  error_count: number;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  error: string | null;
};

export type GalleryUploadJobDetail = GalleryUploadJob & {
  imported_items: FileOverviewItem[];
  errors: string[];
};

export type DocumentUploadResult = {
  items: FileOverviewItem[];
  errors: string[];
};

export type StoredFileMetadata = {
  id: string;
  original_name: string;
  mime_type: string | null;
  file_size_bytes: number | null;
  created_at: string;
  checksum_sha256: string | null;
  source: FileOverviewSource;
  ref_label: string;
  ref_date: string | null;
  tags: string[];
  origin_tag: string;
  width: number | null;
  height: number | null;
  exif_taken_at: string | null;
  exif_camera: string | null;
  uploaded_by_name: string | null;
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

export type UserSummary = {
  id: string;
  first_name: string | null;
  last_name: string | null;
  display_name: string;
  email: string | null;
  preferred_language: string;
  is_active: boolean;
  external_identity_json: Record<string, unknown>;
  tenant_id: string;
  tenant_name: string;
  role_code: string;
  login_enabled: boolean;
  created_at: string;
  updated_at: string;
};

export type AdminTenantUser = {
  user_id: string;
  email: string | null;
  display_name: string;
  role_code: string;
  login_enabled: boolean;
  is_active: boolean;
};

export type AdminSessionInfo = {
  authenticated: boolean;
  admin: { id: string; email: string; display_name: string; role: "owner" | "support" } | null;
};

export type AdminLoginResponse = AdminSessionInfo & {
  mfa: PendingMfaLogin | null;
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
  storage_used_bytes: number;
  storage_quota_bytes: number | null;
  enabled_features: string[];
  plan_code: string | null;
  plan_name: string | null;
  billing_cycle: "monthly" | "yearly";
  user_limit_override: number | null;
  effective_user_limit: number | null;
  plan_storage_bytes: number | null;
  package_storage_bytes: number;
  effective_storage_quota_bytes: number | null;
  storage_quota_manual_override: boolean;
  assigned_storage_packages: AdminTenantStoragePackage[];
  discount_percent: number;
  billing_note: string | null;
  show_on_website: boolean;
};

export type AdminTenantStoragePackage = {
  package_code: string;
  name: string;
  bytes: number;
  quantity: number;
  total_bytes: number;
};

export type AdminStoragePackage = {
  code: string;
  name: string;
  bytes: number;
  price_monthly_rp: number | null;
  price_yearly_rp: number | null;
  sort_order: number;
  is_bookable: boolean;
  tenant_count: number;
};

export type AdminStoragePackageWrite = {
  name: string;
  bytes: number;
  price_monthly_rp: number | null;
  price_yearly_rp: number | null;
  sort_order: number;
  is_bookable: boolean;
};

// JSON-Export/-Import des Preiskatalogs (backend/app/schemas/catalog_config.py).
export type CatalogImportRequest = {
  config: Record<string, unknown>;
  overwrite: boolean;
  base_fingerprint?: string | null;
};

export type CatalogFieldChange = {
  field: string;
  old: unknown;
  new: unknown;
};

export type CatalogImportChange = {
  entity: "feature" | "plan" | "storage_package";
  code: string;
  name: string;
  action: "create" | "update" | "delete" | "deactivate";
  changes: CatalogFieldChange[];
  tenant_count: number;
};

export type CatalogImportPreview = {
  overwrite: boolean;
  changes: CatalogImportChange[];
  errors: string[];
  unchanged_count: number;
  base_fingerprint: string;
};

export type AdminTenantStoragePackageItem = {
  package_code: string;
  quantity: number;
};

export type AdminTenantStoragePackagesUpdate = {
  items: AdminTenantStoragePackageItem[];
};

export type AdminFeature = {
  code: string;
  name: string;
  description: string | null;
  standalone_price_monthly_rp: number | null;
};

export type AdminFeatureUpdate = {
  name: string;
  description: string | null;
  standalone_price_monthly_rp: number | null;
};

export type AdminPlan = {
  code: string;
  name: string;
  price_monthly_rp: number | null;
  price_yearly_rp: number | null;
  included_user_limit: number | null;
  included_storage_bytes: number | null;
  sort_order: number;
  feature_codes: string[];
  description: string | null;
  is_bookable: boolean;
  is_featured: boolean;
  tenant_count: number;
};

export type AdminPlanWrite = {
  name: string;
  price_monthly_rp: number | null;
  price_yearly_rp: number | null;
  included_user_limit: number | null;
  included_storage_bytes: number | null;
  sort_order: number;
  feature_codes: string[];
  description: string | null;
  is_bookable: boolean;
  is_featured: boolean;
  /** Nur beim Anlegen ausgewertet; leer = aus dem Namen erzeugt. */
  code?: string | null;
};

/** Preiskarte der oeffentlichen Website (GET /api/public/plans) - nur buchbare Plaene. */
export type PublicPlan = {
  code: string;
  name: string;
  description: string | null;
  price_monthly_rp: number | null;
  price_yearly_rp: number | null;
  included_user_limit: number | null;
  included_storage_bytes: number | null;
  is_featured: boolean;
  features: { code: string; name: string }[];
};

/** Kunde fuer "Im Einsatz bei" auf der oeffentlichen Website (GET /api/public/customers). */
export type PublicCustomer = {
  name: string;
};

export type AdminTenantSubscriptionUpdate = {
  plan_code: string | null;
  billing_cycle: "monthly" | "yearly";
  user_limit_override: number | null;
  discount_percent: number;
  billing_note: string | null;
};

export type AdminTenantCreate = {
  name: string;
  public_slug: string | null;
  plan_code: string | null;
  billing_cycle: "monthly" | "yearly";
};

export type AdminTenantPage = {
  items: AdminTenantSummary[];
  total: number;
};

// User-facing groupings (see storage_service.py's docstring): uploaded images, other uploads,
// generated PDF/LaTeX exports, and the catch-all "everything else" bucket.
export type StorageCategoryKey = "photos" | "files" | "protocols" | "other";

export type StorageCategoryUsage = {
  key: StorageCategoryKey;
  label: string;
  bytes: number;
};

export type StorageUsageRead = {
  total_bytes: number;
  quota_bytes: number | null;
  categories: StorageCategoryUsage[];
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

// Same backend upload-source enum as FileOverviewSource - reused rather than redeclared
// with its own member order (audit fix, 2026-09-17: a fifth source added to one but not
// the other used to compile fine on both sides, and the un-updated view would silently
// fall through its `?? entry.source` fallback and show the raw enum string instead).
export type UploadPipelineSource = FileOverviewSource;

export type UploadPipelineFileEntry = {
  id: string;
  tenant_id: string;
  tenant_name: string;
  original_name: string;
  mime_type: string | null;
  file_size_bytes: number | null;
  source: UploadPipelineSource;
  origin_tag: string;
  scan_status: string;
  created_at: string;
};

export type UploadPipelineStatusPage = {
  items: UploadPipelineFileEntry[];
  total: number;
};

export type UploadPipelineSummaryEntry = {
  source: UploadPipelineSource;
  scan_status: string;
  count: number;
};

export type AbgabeboxQuarantineEntry = {
  tenant_id: string | null;
  tenant_name: string | null;
  assignment_id: number | null;
  file_name: string;
  age_seconds: number;
  file_size_bytes: number;
};

export type UploadPipelineOverview = {
  summary: UploadPipelineSummaryEntry[];
  files: UploadPipelineStatusPage;
  abgabebox_quarantine: AbgabeboxQuarantineEntry[];
};

export type JobState = "ok" | "running" | "failing" | "overdue" | "never_run";
export type JobCategory = "virus_scan" | "photo_analysis" | "uploads" | "cleanup" | "maintenance" | "backup" | "storage";

export type JobStatusEntry = {
  name: string;
  // false = Job meldet sich, steht aber nicht in backend/app/core/job_registry.py
  registered: boolean;
  kind: "loop" | "worker" | "host_cron" | null;
  service: string | null;
  category: JobCategory | null;
  interval_seconds: number | null;
  max_silence_seconds: number | null;
  state: JobState;
  last_status: "running" | "success" | "failure" | null;
  last_started_at: string | null;
  last_finished_at: string | null;
  last_success_at: string | null;
  last_failure_at: string | null;
  last_heartbeat_at: string | null;
  last_duration_ms: number | null;
  last_error: string | null;
  consecutive_failures: number;
  run_count: number;
  failure_count: number;
};

export type JobStatusOverview = {
  items: JobStatusEntry[];
  generated_at: string;
};

export type JobRunEntry = {
  id: number;
  status: "success" | "failure";
  started_at: string;
  finished_at: string;
  duration_ms: number;
  error: string | null;
};

export type JobRunPage = {
  items: JobRunEntry[];
  total: number;
};

export type HealthStatus = "ok" | "warning" | "critical" | "unknown";

export type ContainerStatusEntry = {
  name: string;
  service: string;
  container_id: string;
  state: string;
  health: string | null;
  health_output: string | null;
  restart_count: number;
  started_at: string | null;
  exit_code: number | null;
  oom_killed: boolean;
  image: string | null;
  version: string | null;
  cpu_percent: number | null;
  memory_bytes: number | null;
  memory_limit_bytes: number | null;
  status: HealthStatus;
  reasons: string[];
};

export type HealthCheckEntry = {
  key: string;
  status: HealthStatus;
  params: Record<string, string | number | null>;
  error: string | null;
};

export type SystemHealthSnapshot = {
  collected_at: string;
  docker_configured: boolean;
  docker_available: boolean;
  docker_error: string | null;
  compose_project: string | null;
  containers: ContainerStatusEntry[];
  checks: HealthCheckEntry[];
};

export type SystemProblem = {
  key: string;
  source: "monitor" | "container" | "check" | "job";
  subject: string;
  reason: string;
  severity: "warning" | "critical";
  title: string;
  message: string;
  first_seen_at: string | null;
};

export type SystemHealthEvent = {
  id: number;
  kind: "problem" | "resolved" | "container_restart";
  subject: string;
  reason: string | null;
  severity: "info" | "warning" | "critical";
  title: string;
  message: string;
  created_at: string;
};

export type SystemStatus = {
  snapshot: SystemHealthSnapshot | null;
  stale: boolean;
  problems: SystemProblem[];
  events: SystemHealthEvent[];
};

export type NotificationSettings = {
  ntfy_enabled: boolean;
  ntfy_server_url: string | null;
  ntfy_topic: string | null;
  ntfy_token_set: boolean;
  admin_url: string | null;
  reminder_hours: number;
  status_token: string | null;
  status_url: string | null;
  last_sent_at: string | null;
  last_send_error: string | null;
  last_send_error_at: string | null;
};

export type NotificationSettingsWrite = {
  ntfy_enabled: boolean;
  ntfy_server_url: string | null;
  ntfy_topic: string | null;
  // null = unverändert, "" = entfernen
  ntfy_token: string | null;
  admin_url: string | null;
  reminder_hours: number;
};

export type NotificationTestResult = {
  ok: boolean;
  error: string | null;
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

export type TableSnapshotTableSummary = {
  table_name: string;
  row_count: number;
  created_at: string;
  is_edited: boolean;
  edited_at?: string | null;
};

export type TableSnapshotCycleSummary = {
  cycle_config_id: string;
  cycle_config_name: string;
  cycle_year: number;
  has_snapshot: boolean;
  tables: TableSnapshotTableSummary[];
};

export type TableSnapshotListReconstructDraft = {
  source: "live" | "snapshot";
  source_cycle_year: number | null;
  definition_values: Record<string, unknown>;
  entries: Record<string, unknown>[];
};

export type TableSnapshotRowsRead = {
  table_name: string;
  cycle_year: number;
  row_count: number;
  is_edited: boolean;
  rows: Record<string, unknown>[];
};

export type ParticipantSummary = {
  id: string;
  tenant_id: string;
  login_enabled?: boolean;
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

/** Zyklus eines Protokolls für die Gruppierung der Liste (nur GET /api/protocols). */
export type ProtocolListCycle = {
  key: string;
  /** null = Vorlage ohne Zyklus, gruppiert nach Kalenderjahr. */
  name: string | null;
  cycle_year: number;
  start_date: string;
  end_date: string;
  is_current: boolean;
};

// POST /api/protocols/{id}/sync-template (mit ?dry_run=true nur Vorschau).
export type ProtocolTemplateSyncResult = {
  applied: boolean;
  added_elements: string[];
  updated_elements: string[];
  removed_elements: string[];
  kept_elements: string[];
  added_blocks: number;
  removed_blocks: number;
  kept_blocks: number;
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
  cycle?: ProtocolListCycle | null;
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
  /** Blocktitel im Export als Untertitel setzen (bis 0113 in configuration_json). */
  title_as_subtitle?: boolean;
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
  /** Werte der Elementdefinition vor jedem Vorlagen-Override (für «weicht vom Default ab»). */
  behavior_defaults?: Partial<Record<TemplateElementBehaviorField, boolean>>;
  sort_index: number;
  render_order: number | null;
  latex_template: string | null;
  configuration_json: Record<string, unknown>;
  created_at: string;
};

export type FineTariff = {
  account_id: string | null;
  amount_late: number;
  amount_absent: number;
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
  /** Alle Verantwortlichen (z. B. mehrere Personen eines Ämtlis). Leer = nur assigned_participant_id. */
  assigned_participant_ids?: string[];
  /** Herkunft aus einem Aufgabenpaket. */
  task_package_id?: string | null;
  task_package_name?: string | null;
  cycle_year?: number | null;
  overridden_fields?: string[];
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
  duplicate_warning?: string | null;
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
  public_reference_ids?: { lists?: Record<string, string>; finance_accounts?: Record<string, string>; events?: Record<string, string> };
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
  status: "pending" | "collected" | "deleted";
  collected_at: string | null;
  collected_transaction_id: string | null;
  closed_in_protocol_id: string | null;
  collected_by_user_id: string | null;
  collected_by_display_name: string | null;
  can_reopen: boolean;
  /** Löschen mit Begründung (Busse aus abgeschlossenem Protokoll). */
  delete_comment?: string | null;
  deleted_at?: string | null;
  deleted_by_display_name?: string | null;
  delete_requires_reason?: boolean;
  can_restore?: boolean;
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
  /** Pro Person und Währung eine Zeile (MAIN-BE-019); participant_key fasst eine Person zusammen. */
  fines_by_participant: { name: string; count: number; amount: number; currency?: string; participant_key?: string }[];
  fines_by_type: { fine_type: string; label: string; count: number; amount: number; currency?: string }[];
  finance_by_month: { month: string; account_id: string; account_name: string; income: number; expenses: number; net: number }[];
  participants_total: number;
  participants_active: number;
  protocols_total: number;
  cycles: { cycle_config_id: string; cycle_config_name: string; cycle_year: number; label: string }[];
  groups_stats: { group_name: string; cycle_config_id: string | null; cycle_year: number | null; session_count: number; session_count_with_participants: number; avg_participants: number }[];
};

// ── Aufgabenpakete ───────────────────────────────────────────────────────

export type TaskPackageResponsible = {
  list_definition_id?: string | null;
  list_entry_id?: string | null;
  participant_id?: string | null;
};

export type TaskPackageRecurrenceType = "once" | "monthly" | "weekly" | "events";

export type TaskPackageRecurrence = {
  type: TaskPackageRecurrenceType;
  day_of_month?: number | null;
  /** 0 = Montag ... 6 = Sonntag */
  weekday?: number | null;
  event_tag?: string | null;
};

export type TaskPackageDueRuleType = "none" | "fixed" | "offset";

export type TaskPackageDueRule = {
  type: TaskPackageDueRuleType;
  month?: number | null;
  day?: number | null;
  offset_days?: number | null;
};

export type TaskPackageItem = {
  id: string;
  sort_index: number;
  task: string;
  reference_link: string | null;
  tags: string[];
  responsible: TaskPackageResponsible[];
  recurrence: TaskPackageRecurrence;
  due_rule: TaskPackageDueRule;
};

export type TaskPackageCycle = {
  id: string;
  cycle_config_id: string;
  cycle_config_name: string;
  start_cycle_year: number;
  current_cycle_year: number;
  current_cycle_label: string;
};

export type TaskPackage = {
  id: string;
  name: string;
  description: string | null;
  is_active: boolean;
  cycles: TaskPackageCycle[];
  items: TaskPackageItem[];
  open_todo_count: number;
  todo_count: number;
  created_at: string;
  updated_at: string;
};

export type TaskPackagePreviewEntry = {
  item_id: string;
  task: string;
  occurrence_key: string;
  occurrence_date: string;
  due_date: string | null;
  assignee_names: string[];
  exists: boolean;
};

export type TaskPackagePreview = {
  cycle_config_id: string;
  cycle_year: number;
  cycle_label: string;
  entries: TaskPackagePreviewEntry[];
};

export type TaskPackageTodoDeleteMode = "all" | "future" | "none";


// --- Wartung (backend/app/schemas/maintenance.py) ---------------------------------------------

export type PublicMaintenanceStatus = {
  active: boolean;
  partial: boolean;
  block_scope: "all" | "writes" | "uploads" | null;
  reason_code: string | null;
  messages: Record<string, string>;
  affected_features: string[];
  started_at: string | null;
  estimate_state: "estimating" | "estimated" | "overdue" | null;
  estimated_end_at: string | null;
  remaining_low_seconds: number | null;
  remaining_high_seconds: number | null;
  upcoming: { starts_at: string | null; ends_at: string | null; kind: string; reason_code: string; messages: Record<string, string> }[];
  updated_at: string;
};

export type MaintenanceState = "scheduled" | "preparing" | "active" | "verifying" | "completed" | "failed" | "overdue" | "cancelled";

export type MaintenanceCondition = { key: string; satisfied: boolean; reason: string; params: Record<string, unknown> };

export type MaintenanceEvent = {
  id: number;
  created_at: string;
  kind: string;
  actor_email: string | null;
  from_state: string | null;
  to_state: string | null;
  details: Record<string, unknown>;
};

export type MaintenanceEstimate = {
  scope?: string;
  remaining_low_seconds: number;
  remaining_high_seconds: number;
  safety_margin_seconds: number;
  components?: Record<string, number>;
  rate_bytes_per_second?: number;
  rate_basis?: string;
  reserve_basis?: string;
  confidence?: string;
};

export type MaintenanceWindow = {
  id: string;
  kind: "full" | "partial";
  block_scope: "all" | "writes" | "uploads";
  state: MaintenanceState;
  reason_code: string;
  affected_features: string[];
  public_message: Record<string, string>;
  internal_note: string | null;
  source_job_type: string | null;
  source_job_id: string | null;
  scheduled_start_at: string | null;
  scheduled_end_at: string | null;
  started_at: string | null;
  ended_at: string | null;
  estimate: MaintenanceEstimate | null;
  estimated_end_at: string | null;
  original_estimated_end_at: string | null;
  safety_margin_seconds: number | null;
  estimate_updated_at: string | null;
  progress: Record<string, number | string>;
  release_conditions: { key: string; params?: Record<string, unknown> }[];
  warnings: unknown[];
  last_error: string | null;
  created_by_email: string | null;
  created_at: string;
  updated_at: string;
  conditions: MaintenanceCondition[];
  events: MaintenanceEvent[];
};

export type MaintenanceOverview = {
  blocking: boolean;
  full_active: boolean;
  current: MaintenanceWindow[];
  scheduled: MaintenanceWindow[];
  history: MaintenanceWindow[];
  history_total: number;
};

// --- Storage (backend/app/schemas/storage_admin.py) -------------------------------------------

export type StorageProvider = "filesystem" | "garage_local" | "aws_s3" | "hetzner" | "s3_compatible";

export type StorageProfile = {
  id: string;
  name: string;
  provider: StorageProvider;
  endpoint_url: string | null;
  region: string | null;
  bucket: string | null;
  abgabebox_bucket: string | null;
  prefix: string;
  addressing_style: "auto" | "path" | "virtual";
  access_key_masked: string | null;
  has_secret_key: boolean;
  has_restricted_credentials: boolean;
  tls_verify: boolean;
  has_ca_bundle: boolean;
  is_enabled: boolean;
  is_builtin: boolean;
  is_active: boolean;
  in_use_by_migration: boolean;
  pinned_generations: number[];
  config_version: number;
  last_test_at: string | null;
  last_test_ok: boolean | null;
  last_test_error: string | null;
  created_at: string;
  updated_at: string;
};

export type StorageConnectionTest = {
  ok: boolean;
  main: Record<string, boolean | number> | null;
  abgabebox: Record<string, boolean | number> | null;
  error: string | null;
  restricted_credentials: boolean;
};

export type StorageMigrationState =
  | "pending" | "preflight" | "awaiting_confirmation" | "inventory" | "copying" | "catching_up" | "verifying"
  | "ready_for_cutover" | "cutting_over" | "observing" | "completed" | "paused" | "retrying" | "failed" | "cancelled"
  | "rollback_required";

export type StorageMigrationEvent = {
  id: number;
  created_at: string;
  level: "info" | "warning" | "error";
  kind: string;
  actor_email: string | null;
  from_state: string | null;
  to_state: string | null;
  message: string | null;
  details: Record<string, unknown>;
};

export type StorageMigration = {
  id: string;
  kind: "initial" | "live";
  state: StorageMigrationState;
  resume_state: string | null;
  source_profile_name: string;
  source_provider: StorageProvider;
  source_generation: number;
  target_profile_name: string;
  target_provider: StorageProvider;
  target_generation: number;
  requested_by_email: string | null;
  options: Record<string, unknown>;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  phase_started_at: string | null;
  heartbeat_at: string | null;
  checkpoint_at: string | null;
  worker_active: boolean;
  total_objects: number;
  total_bytes: number;
  copied_objects: number;
  copied_bytes: number;
  verified_objects: number;
  failed_objects: number;
  status_counts: Record<string, { objects: number; bytes: number }>;
  current_bps: number | null;
  average_bps: number | null;
  eta_seconds: number | null;
  estimate: { full?: MaintenanceEstimate | null; cutover?: MaintenanceEstimate | null } | null;
  live_estimate: MaintenanceEstimate | null;
  last_error: string | null;
  attempt: number;
  pause_requested: boolean;
  cancel_requested: boolean;
  cutover_confirmed_at: string | null;
  cutover_committed_at: string | null;
  needs_cutover_confirmation: boolean;
  reference_check: { references: number; missing_count: number; unreferenced_count: number } | null;
  maintenance_window_id: string | null;
  final_integrity_ok: boolean;
  events: StorageMigrationEvent[];
};

export type StorageGeneration = {
  id: number;
  profile_id: string;
  profile_name: string;
  generation: number;
  status: "preparing" | "active" | "retained" | "abandoned" | "purge_requested" | "purging" | "purged";
  object_count: number | null;
  total_bytes: number | null;
  created_at: string;
  activated_at: string | null;
  deactivated_at: string | null;
  retain_until: string | null;
  purge_requested_by: string | null;
  purged_at: string | null;
  purge_error: string | null;
};

export type StorageOverview = {
  active_profile: StorageProfile;
  active_generation: number;
  write_fenced: boolean;
  fence_reason: string | null;
  credentials_key_configured: boolean;
  local_s3: { needed: boolean; reason: string; configured: boolean; requested_until: string | null };
  open_migration: StorageMigration | null;
  generations: StorageGeneration[];
  profiles: StorageProfile[];
};

// --- Backups (Plattform-Admin, /api/admin/backups, /api/admin/restores) ---------------------------

export type BackupJobState = "queued" | "preparing" | "running" | "verifying" | "completed" | "partial" | "failed" | "cancelled" | "interrupted";
export type BackupJobKind = "backup" | "verify" | "restore_test" | "retention";
export type BackupTrigger = "schedule" | "manual" | "pre_restore" | "pre_deploy" | "cli";
export type RestoreJobState = "queued" | "preparing" | "running" | "verifying" | "cutover" | "completed" | "failed" | "cancelled" | "interrupted" | "rolled_back";

export type BackupProblem = { code: string; severity: "warning" | "critical"; params: Record<string, string | number | null> };

export type BackupSetWarning = { code: string; count: number | null; items: Array<Record<string, string>> };

export type BackupSet = {
  id: string;
  archive_name: string;
  state: "completed" | "partial" | "failed" | "invalid" | "pruned";
  trigger: BackupTrigger;
  protected: boolean;
  protected_reason: string | null;
  snapshot_at: string;
  finished_at: string | null;
  app_version: string | null;
  alembic_revision: string | null;
  generation: number | null;
  profile_name: string | null;
  profile_provider: string | null;
  db_dump_bytes: number | null;
  object_count: number;
  object_bytes: number;
  new_object_count: number;
  new_object_bytes: number;
  deduplicated_bytes: number | null;
  duration_seconds: number | null;
  verify_state: "unverified" | "verified" | "failed";
  verified_at: string | null;
  restore_test_state: "untested" | "passed" | "failed";
  restore_tested_at: string | null;
  warnings: BackupSetWarning[];
  tenant_count: number;
  reconstructed: boolean;
};

export type BackupTenant = { id: number; public_id: string | null; name: string; users: number; objects: number; bytes: number };

export type BackupJob = {
  id: string;
  kind: BackupJobKind;
  trigger: BackupTrigger;
  state: BackupJobState;
  requested_by_email: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  heartbeat_at: string | null;
  worker_active: boolean;
  attempt: number;
  cancel_requested: boolean;
  progress: Record<string, string | number | null>;
  error_code: string | null;
  error_message: string | null;
  warning_count: number;
  duration_seconds: number | null;
  backup_set: BackupSet | null;
};

export type BackupEvent = {
  id: number;
  created_at: string;
  level: "info" | "warning" | "error";
  kind: string;
  actor_email: string | null;
  message: string | null;
  details: Record<string, unknown>;
};

export type BackupJobDetail = BackupJob & { result: Record<string, unknown> | null; events: BackupEvent[]; tenants: BackupTenant[] };

export type BackupJobPage = { items: BackupJob[]; total: number; offset: number; limit: number };

export type BackupRepositoryStatus = {
  ok: boolean | null;
  checked_at: string | null;
  last_ok_at: string | null;
  error_code: string | null;
  error: string | null;
  repository_id: string | null;
  encryption: string | null;
  borg_version: string | null;
  stored_bytes: number | null;
  original_bytes: number | null;
  deduplicated_bytes: number | null;
  quota_bytes: number | null;
  used_percent: number | null;
  staging_free_bytes: number | null;
  staging_total_bytes: number | null;
  last_gc_at: string | null;
  last_verify_at: string | null;
  last_verify_ok: boolean | null;
  last_restore_test_at: string | null;
  last_restore_test_ok: boolean | null;
};

export type RestoreJob = {
  id: string;
  kind: "full" | "tenant_copy";
  state: RestoreJobState;
  archive_name: string;
  backup_set_id: string | null;
  options: Record<string, unknown>;
  plan: Record<string, unknown>;
  requested_by_email: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  heartbeat_at: string | null;
  worker_active: boolean;
  progress: Record<string, string | number | null>;
  error_code: string | null;
  error_message: string | null;
  result: Record<string, unknown> | null;
  cancel_requested: boolean;
  events: BackupEvent[];
};

export type BackupStatus = {
  enabled: boolean;
  overall: "ok" | "warning" | "critical" | "disabled";
  problems: BackupProblem[];
  last_success: BackupSet | null;
  last_failure: BackupJob | null;
  next_backup_at: string | null;
  restore_point_count: number;
  protected_count: number;
  latest_object_bytes: number | null;
  latest_db_bytes: number | null;
  repository: BackupRepositoryStatus;
  last_verified_at: string | null;
  last_verified_archive: string | null;
  last_restore_test_at: string | null;
  last_restore_test_archive: string | null;
  current_job: BackupJob | null;
  current_restore: RestoreJob | null;
  worker_heartbeat_at: string | null;
  worker_alive: boolean;
};

export type BackupSettings = {
  schedule_enabled: boolean;
  interval_hours: number;
  schedule_offset_minutes: number;
  keep_within_days: number;
  keep_daily: number;
  keep_weekly: number;
  keep_monthly: number;
  verify_interval_hours: number;
  verify_sample_objects: number;
  restore_test_interval_days: number;
  success_notification: "off" | "daily" | "each";
  worker_config: Record<string, string | number | boolean | null>;
  repository: BackupRepositoryStatus;
  ntfy_configured: boolean;
  updated_at: string;
  updated_by_email: string | null;
};

export type RestorePreview = {
  kind: "full" | "tenant_copy";
  backup_set: BackupSet;
  schema_state: "same" | "upgrade" | "newer" | "unknown";
  schema_revision: string | null;
  schema_head: string | null;
  target_profile_name: string | null;
  target_profile_provider: string | null;
  tenant: BackupTenant | null;
  new_name: string | null;
  name_conflict: boolean;
  steps: string[];
  risks: string[];
  blockers: string[];
  confirmation_phrase: string;
  requires_totp: boolean;
  estimated_bytes: number;
};
