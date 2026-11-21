"use client";

import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import type { Route } from "next";
import { usePathname, useRouter } from "next/navigation";
import { useLocale, useTranslations } from "next-intl";

import { AdminAvatar, BillingCycleToggle, formatPlanPrice, PlanBadge, PlanOption, planTones } from "@/components/admin/admin-plan-utils";
import { ColumnPicker, useColumnVisibility, type ColumnDef } from "@/components/admin/column-picker";
import { ActionMenu } from "@/components/ui/action-menu";
import { Badge } from "@/components/ui/badge";
import { DataTable } from "@/components/ui/data-table";
import { FilterTabs } from "@/components/ui/filter-tabs";
import { Modal } from "@/components/ui/modal";
import { Pagination } from "@/components/ui/pagination";
import { SearchInput } from "@/components/ui/search-input";
import { TenantCloneModal, TenantExportModal, useTenantDelete } from "@/components/admin/tenant-detail/tenant-action-modals";
import { browserApiFetch } from "@/lib/api/client";
import { stepUpFetch } from "@/lib/admin-step-up";
import { useToast } from "@/contexts/toast-context";
import { formatFileSize, formatPercentNumber } from "@/lib/utils/format";
import {
  DEFAULT_TENANT_VIEW,
  STORAGE_WARNING_RATIO,
  TenantListView,
  TenantSortKey,
  TenantStatusFilter,
  tenantListQuery,
} from "@/lib/admin/tenant-list";
import { TenantStatusBadges } from "@/components/admin/tenant-detail/tenant-status-badges";
import { AdminPlan, AdminTenantCreate, AdminTenantPage, AdminTenantSummary } from "@/types/api";


type Props = {
  initialPage: AdminTenantPage;
  initialPlans: AdminPlan[];
  initialPlanFilter?: string;
  /** Sortierung/Filter aus der URL (Admin-Redesign §5.1) - Mandantennamen sind keine Personendaten. */
  initialView?: Partial<TenantListView>;
};


const PAGE_SIZE = 50;


const emptyCreateForm: AdminTenantCreate = {
  name: "",
  plan_code: null,
  billing_cycle: "monthly",
};

export function AdminTenantManagement({ initialPage, initialPlans, initialPlanFilter = "", initialView }: Props) {
  const router = useRouter();
  const pathname = usePathname();
  const t = useTranslations("admin.tenants");
  const tPlans = useTranslations("admin.plans");
  const tDetail = useTranslations("adminTenantDetail");
  const locale = useLocale();
  const showToast = useToast();
  const [page, setPage] = useState(initialPage);
  const [offset, setOffset] = useState(0);
  const tenants = page.items;
  const [modalOpen, setModalOpen] = useState(false);
  const [createForm, setCreateForm] = useState(emptyCreateForm);
  const [createBusy, setCreateBusy] = useState(false);
  const [view, setView] = useState<TenantListView>({ ...DEFAULT_TENANT_VIEW, ...initialView });
  const [search, setSearch] = useState(view.q);
  const [plans, setPlans] = useState<AdminPlan[]>(initialPlans);
  const [planFilter, setPlanFilter] = useState(initialPlanFilter);
  const confirmDeleteTenant = useTenantDelete();
  const [cloneTenant, setCloneTenant] = useState<AdminTenantSummary | null>(null);
  const [exportTenant, setExportTenant] = useState<AdminTenantSummary | null>(null);
  const [importModalOpen, setImportModalOpen] = useState(false);
  const [importName, setImportName] = useState("");
  const [importFile, setImportFile] = useState<File | null>(null);
  const [importPassword, setImportPassword] = useState("");
  const [importBusy, setImportBusy] = useState(false);
  const [importWarnings, setImportWarnings] = useState<string[] | null>(null);
  const [loading, setLoading] = useState(false);

  // Server now applies `search` before pagination (audit A1, 2026-08-16 - fetchPage below
  // sends it as `q`), so page.items is already the matching set for the current page.
  const visibleTenants = tenants;

  const tones = useMemo(() => planTones(plans), [plans]);
  const plansByCode = useMemo(() => new Map(plans.map((plan) => [plan.code, plan])), [plans]);
  const bookablePlans = useMemo(() => plans.filter((plan) => plan.is_bookable), [plans]);
  const totalTenantCount = plans.reduce((sum, plan) => sum + plan.tenant_count, 0);

  async function fetchPage(nextOffset: number, query: string, plan: string = planFilter) {
    setLoading(true);
    try {
      const params = tenantListQuery({ ...view, q: query }, plan);
      // Zustand in der URL (teilen, Zurück-Taste): nur Mandantenname, Plan- und Filter-Codes.
      const urlQuery = params.toString();
      // Nur ersetzen, wenn sich die Adresse wirklich ändert und die Liste noch angezeigt wird: ein
      // verspätetes replace (Such-Debounce) überschrieb sonst den Klick auf einen Mandanten.
      if (window.location.pathname === pathname && window.location.search.replace(/^\?/, "") !== urlQuery) {
        router.replace((urlQuery ? `${pathname}?${urlQuery}` : pathname) as Route, { scroll: false });
      }
      params.set("limit", String(PAGE_SIZE));
      params.set("offset", String(nextOffset));
      const result = await browserApiFetch<AdminTenantPage>(`/api/admin/tenants?${params.toString()}`);
      setPage(result);
    } catch {
      // keep showing the previous page rather than blanking the table on a transient error
    } finally {
      setLoading(false);
    }
  }

  // Zähler der Filter-Chips (tenant_count pro Plan) nach Anlegen/Löschen/Planwechsel auffrischen.
  async function reloadPlans() {
    try {
      setPlans(await browserApiFetch<AdminPlan[]>("/api/admin/plans"));
    } catch {
      // Zähler bleiben dann auf dem letzten Stand
    }
  }

  function changePlanFilter(value: string) {
    setPlanFilter(value);
    if (offset !== 0) {
      setOffset(0);
    } else {
      void fetchPage(0, search, value);
    }
  }

  useEffect(() => {
    void fetchPage(offset, search);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [offset]);

  // Sortierung/Filter geändert: von vorne laden.
  const viewKey = `${view.sort}:${view.dir}:${view.status}:${view.storageFull}`;
  const firstViewRender = useRef(true);
  useEffect(() => {
    if (firstViewRender.current) {
      firstViewRender.current = false;
      return;
    }
    if (offset !== 0) setOffset(0);
    else void fetchPage(0, search);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [viewKey]);

  // Spaltenwahl (1.5.1), je Admin im Browser gespeichert
  const columnDefs: ColumnDef[] = [
    { key: "image", label: t("colImage") },
    { key: "name", label: t("colTenant"), required: true },
    { key: "plan", label: t("colPlan") },
    { key: "participants", label: t("colParticipants") },
    { key: "users", label: t("colUsers") },
    { key: "storage", label: t("colStorage") },
    { key: "created", label: t("colCreatedAt") },
  ];
  const cols = useColumnVisibility("tenants", columnDefs);

  function sortColumn(key: TenantSortKey, label: string) {
    const active = view.sort === key;
    return {
      key,
      label,
      sortable: true,
      sortDirection: active ? view.dir : null,
      onSort: () =>
        setView((current) => ({
          ...current,
          sort: key,
          // Erster Klick: Text aufsteigend, Zahlen/Datum absteigend (grösste/neueste zuerst)
          dir: current.sort === key ? (current.dir === "asc" ? "desc" : "asc") : key === "name" || key === "plan" ? "asc" : "desc",
        })),
    };
  }

  function openDetail(tenant: AdminTenantSummary) {
    router.push(`/admin/tenants/${tenant.id}` as Route);
  }

  // Debounced re-fetch from offset 0 whenever the search text changes - see the identical
  // pattern in admin-user-management.tsx.
  const firstSearchRender = useRef(true);
  useEffect(() => {
    // Beim Laden lädt schon der offset-Effekt oben - kein zweiter Abruf
    if (firstSearchRender.current) {
      firstSearchRender.current = false;
      return;
    }
    const timer = window.setTimeout(() => {
      if (offset !== 0) {
        setOffset(0);
      } else {
        void fetchPage(0, search);
      }
    }, 300);
    return () => window.clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search]);

  function openCreate() {
    setCreateForm({ ...emptyCreateForm, plan_code: bookablePlans.find((plan) => plan.tenant_count > 0)?.code ?? bookablePlans[0]?.code ?? null });
    setModalOpen(true);
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setCreateBusy(true);
    try {
      const payload: AdminTenantCreate = {
        name: createForm.name.trim(),
        plan_code: createForm.plan_code,
        billing_cycle: createForm.billing_cycle,
      };
      await browserApiFetch<AdminTenantSummary>("/api/admin/tenants", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      await Promise.all([fetchPage(offset, search), reloadPlans()]);
      setModalOpen(false);
      showToast(t("created"), "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("createFailed"), "error");
    } finally {
      setCreateBusy(false);
    }
  }

  function openClone(tenant: AdminTenantSummary) {
    setCloneTenant(tenant);
  }

  function openExport(tenant: AdminTenantSummary) {
    setExportTenant(tenant);
  }

  async function deleteTenant(tenant: AdminTenantSummary) {
    if (!(await confirmDeleteTenant(tenant))) return;
    // Deleting the last item on a page would strand the view past the new end - fall
    // back a page first if that's about to happen (changing offset re-triggers the load).
    if (tenants.length === 1 && offset > 0) {
      setOffset(offset - PAGE_SIZE);
    } else {
      await fetchPage(offset, search);
    }
    void reloadPlans();
  }

  function openImport() {
    setImportName("");
    setImportFile(null);
    setImportPassword("");
    setImportModalOpen(true);
  }

  async function submitImport(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!importFile) return;
    setImportBusy(true);
    try {
      const formData = new FormData();
      formData.append("new_name", importName);
      formData.append("file", importFile);
      if (importPassword) formData.append("password", importPassword);
      const { ticket } = await stepUpFetch<{ ticket: string }>("tenant-import", "/api/admin/tenants/import/authorize", {
        method: "POST",
        body: JSON.stringify({ new_name: importName }),
      });
      const result = await browserApiFetch<{ tenant: AdminTenantSummary; warnings: string[] }>(
        "/api/admin/tenants/import",
        // Uploads/entpackt/importiert bis zu MAX_TENANT_IMPORT_UPLOAD_BYTES (2 GB, siehe
        // backend/app/api/routes/admin.py) - browserApiFetch's Default-Timeout von 15s reicht
        // dafuer bei weitem nicht, was zuvor als "Zeitueberschreitung beim Server" fehlschlug.
        // Passkey-Bestätigung (Zweck tenant-import) für ein einmaliges Import-Ticket, das an den
        // Namen gebunden ist; der Upload (bis 2 GB) trägt nur das Ticket im Header (Security-Review M2).
        { method: "POST", body: formData, signal: AbortSignal.timeout(600_000), headers: { "X-Hocx-Import-Ticket": ticket } }
      );
      await Promise.all([fetchPage(offset, search), reloadPlans()]);
      setImportModalOpen(false);
      if (result.warnings.length > 0) {
        // Warnings only ever went to the browser console before this fix (audit finding,
        // 2026-08-25) - the toast pointed there but most admins never open devtools, so
        // real issues (skipped rows, missing source files, ...) went unseen in practice.
        // Shown in a dedicated modal now instead.
        showToast(t("importedWithWarnings", { count: result.warnings.length }), "success");
        setImportWarnings(result.warnings);
      } else {
        showToast(t("imported"), "success");
      }
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("importFailed"), "error");
    } finally {
      setImportBusy(false);
    }
  }

  return (
    <div className="grid">
      <div className="page-header">
        <div>
          <h1 className="page-title">{t("title")}</h1>
          <p className="muted">{t("description")}</p>
        </div>
        <div className="table-toolbar-actions">
          <ColumnPicker columns={columnDefs} isVisible={cols.isVisible} onToggle={cols.toggle} />
          <button type="button" className="button-secondary" onClick={openImport}>
            {t("importTenant")}
          </button>
          <button type="button" className="button-primary" onClick={openCreate}>
            {t("newTenant")}
          </button>
        </div>
      </div>

      <article className="card admin-tenant-filter-card">
        <SearchInput value={search} onChange={setSearch} placeholder={t("searchPlaceholder")} />
        {plans.length > 0 ? (
          <FilterTabs
            variant="chips"
            value={planFilter}
            onChange={changePlanFilter}
            options={[
              { value: "", label: t("all"), count: totalTenantCount },
              ...plans.map((plan) => ({ value: plan.code, label: plan.name, count: plan.tenant_count })),
            ]}
          />
        ) : null}
        <FilterTabs
          variant="chips"
          value={view.status}
          onChange={(value) => setView((current) => ({ ...current, status: value as TenantStatusFilter }))}
          options={[
            { value: "", label: tDetail("statusFilter.all") },
            { value: "read_only", label: tDetail("status.readOnly") },
            { value: "contract_ending", label: tDetail("status.contractEnding") },
            { value: "unverified", label: tDetail("status.unverified") },
          ]}
        />
        <label className="checkbox-row">
          <input
            type="checkbox"
            checked={view.storageFull}
            onChange={(event) => setView((current) => ({ ...current, storageFull: event.target.checked }))}
          />
          <span>{tDetail("statusFilter.storageFull")}</span>
        </label>
      </article>

      <DataTable
        columns={[
          cols.isVisible("image") ? t("colImage") : null,
          sortColumn("name", t("colTenant")),
          cols.isVisible("plan") ? sortColumn("plan", t("colPlan")) : null,
          cols.isVisible("participants") ? t("colParticipants") : null,
          cols.isVisible("users") ? sortColumn("users", t("colUsers")) : null,
          cols.isVisible("storage") ? sortColumn("storage", t("colStorage")) : null,
          cols.isVisible("created") ? sortColumn("created", t("colCreatedAt")) : null,
          "",
        ].filter((column) => column !== null)}
        emptyMessage={loading ? t("loading") : t("noTenantsFound")}
      >
        {visibleTenants.map((tenant) => {
          const plan = tenant.plan_code ? plansByCode.get(tenant.plan_code) : undefined;
          const usageRatio = tenant.storage_quota_bytes ? tenant.storage_used_bytes / tenant.storage_quota_bytes : 0;
          const storageState = usageRatio > 1 ? "over" : usageRatio >= STORAGE_WARNING_RATIO ? "warning" : "ok";
          return (
            <tr key={tenant.id} className="table-row-clickable" onClick={() => openDetail(tenant)} /* a11y-ok: Maus-Abkürzung, Tastatur über table-row-link (Name) */>
              {cols.isVisible("image") ? (
                <td>
                  <AdminAvatar name={tenant.name} imageUrl={tenant.profile_image_url} toneKey={tenant.id} />
                </td>
              ) : null}
              <td>
                {/* Tastatur: Name als Knopf, die Zeile bleibt für die Maus klickbar */}
                <Link href={`/admin/tenants/${tenant.id}` as Route} className="table-row-link" onClick={(event) => event.stopPropagation()}>
                  {tenant.name}
                </Link>
                <TenantStatusBadges tenant={tenant} compact />
              </td>
              {cols.isVisible("plan") ? <td>
                {tenant.plan_code ? (
                  <PlanBadge name={tenant.plan_name ?? tenant.plan_code} tone={tones.get(tenant.plan_code) ?? "neutral"} />
                ) : (
                  <span className="muted">–</span>
                )}
                <div className="muted admin-cell-sub">{formatPlanPrice(plan, tenant.billing_cycle, tPlans)}</div>
                {tenant.discount_percent > 0 ? (
                  <div className="admin-tenant-discount">
                    <Badge variant="success">{t("discountBadge", { percent: formatPercentNumber(tenant.discount_percent, locale) })}</Badge>
                  </div>
                ) : null}
              </td> : null}
              {cols.isVisible("participants") ? <td className="admin-cell-number">{tenant.participant_count}</td> : null}
              {cols.isVisible("users") ? <td className="admin-cell-number">{tenant.user_count}</td> : null}
              {cols.isVisible("storage") ? <td>
                {tenant.storage_quota_bytes ? (
                  <div className={`admin-storage-cell admin-storage-${storageState}`}>
                    <div className="admin-storage-bar">
                      <div className="admin-storage-bar-fill" style={{ width: `${Math.min(usageRatio * 100, 100)}%` }} />
                    </div>
                    <div className="admin-storage-label">
                      {formatFileSize(tenant.storage_used_bytes)} / {formatFileSize(tenant.storage_quota_bytes)}
                    </div>
                  </div>
                ) : (
                  <div className="admin-storage-cell">
                    <div className="admin-storage-bar admin-storage-bar-unlimited" />
                    <div className="admin-storage-label">{t("noLimitUsage", { used: formatFileSize(tenant.storage_used_bytes) })}</div>
                  </div>
                )}
              </td> : null}
              {cols.isVisible("created") ? <td className="admin-cell-number">{new Date(tenant.created_at).toLocaleDateString(locale)}</td> : null}
              <td onClick={(event) => event.stopPropagation()}>
                <ActionMenu
                  items={[
                    { label: t("settings"), onClick: () => openDetail(tenant) },
                    { label: t("clone"), onClick: () => openClone(tenant) },
                    { label: t("export"), onClick: () => openExport(tenant) },
                    { label: t("delete"), onClick: () => deleteTenant(tenant), danger: true },
                  ]}
                />
              </td>
            </tr>
          );
        })}
      </DataTable>

      <Pagination offset={offset} limit={PAGE_SIZE} total={page.total} onOffsetChange={setOffset} />

      <Modal open={modalOpen} onClose={() => setModalOpen(false)} title={t("newTenant")} description={t("newTenantDescription")}>
        <form className="grid" onSubmit={submit}>
          <label className="field-stack">
            <span className="field-label">{t("tenantName")}</span>
            <input
              value={createForm.name}
              onChange={(event) => setCreateForm((current) => ({ ...current, name: event.target.value }))}
              placeholder={t("tenantNamePlaceholder")}
              required
            />
          </label>
          <div className="field-stack">
            <span className="field-label">{t("plan")}</span>
            <div className="admin-plan-options" role="radiogroup" aria-label={t("plan")}>
              {bookablePlans.map((plan) => (
                <PlanOption
                  key={plan.code}
                  plan={plan}
                  name="create-plan"
                  checked={createForm.plan_code === plan.code}
                  cycle={createForm.billing_cycle}
                  onSelect={() => setCreateForm((current) => ({ ...current, plan_code: plan.code }))}
                />
              ))}
            </div>
            <span className="field-help">{t("nonBookablePlansHint")}</span>
          </div>
          <div className="field-stack">
            <span className="field-label">{t("billing")}</span>
            <BillingCycleToggle value={createForm.billing_cycle} onChange={(billing_cycle) => setCreateForm((current) => ({ ...current, billing_cycle }))} />
          </div>
          <div className="modal-actions">
            <button type="button" className="button-ghost" onClick={() => setModalOpen(false)}>
              {t("cancel")}
            </button>
            <button type="submit" className="button-primary" disabled={createBusy || createForm.name.trim() === ""}>
              {createBusy ? t("creating") : t("createTenant")}
            </button>
          </div>
        </form>
      </Modal>

      <TenantCloneModal
        tenant={cloneTenant}
        onClose={() => setCloneTenant(null)}
        onCloned={async () => {
          await Promise.all([fetchPage(offset, search), reloadPlans()]);
        }}
      />
      <TenantExportModal tenant={exportTenant} onClose={() => setExportTenant(null)} />




      <Modal
        open={importModalOpen}
        onClose={() => {
          if (!importBusy) setImportModalOpen(false);
        }}
        title={t("importTenant")}
        description={t("importDescription")}
      >
        <form className="grid" onSubmit={submitImport}>
          <label className="field-stack">
            <span className="field-label">{t("nameOfNewTenant")}</span>
            <input value={importName} onChange={(event) => setImportName(event.target.value)} disabled={importBusy} required />
          </label>
          <label className="field-stack">
            <span className="field-label">{t("exportFile")}</span>
            <input
              type="file"
              accept=".hocxenc,.zip"
              onChange={(event) => setImportFile(event.target.files?.[0] ?? null)}
              disabled={importBusy}
              required
            />
          </label>
          <label className="field-stack">
            <span className="field-label">{t("importPasswordLabel")}</span>
            <input
              type="password"
              autoComplete="off"
              value={importPassword}
              onChange={(event) => setImportPassword(event.target.value)}
              disabled={importBusy}
            />
            <span className="field-help">{t("importPasswordHelp")}</span>
          </label>
          {importBusy ? (
            <div className="tenant-import-status" role="status" aria-live="polite">
              <div className="tenant-import-status-copy">
                <span className="tenant-import-upload-icon" aria-hidden="true">↑</span>
                <span>
                  <strong>{t("uploadingAndProcessing")}</strong>
                  <span className="tenant-import-filename">{importFile?.name}</span>
                </span>
              </div>
              <div
                className="tenant-import-progress-track"
                role="progressbar"
                aria-label={t("uploadAndImportRunning")}
                aria-valuetext={t("uploadAndImportRunning")}
              >
                <span className="tenant-import-progress-bar" />
              </div>
              <span className="tenant-import-status-hint">{t("mayTakeAMoment")}</span>
            </div>
          ) : null}
          <div className="modal-actions">
            <button type="button" className="button-ghost" onClick={() => setImportModalOpen(false)} disabled={importBusy}>
              {t("cancel")}
            </button>
            <button type="submit" className="button-primary" disabled={importBusy || !importFile}>
              {importBusy ? t("importing") : t("import")}
            </button>
          </div>
        </form>
      </Modal>

      <Modal
        open={importWarnings !== null}
        onClose={() => setImportWarnings(null)}
        title={t("importNotesTitle")}
        description={t("importNotesDescription")}
      >
        <ul className="grid">
          {(importWarnings ?? []).map((warning, index) => (
            <li key={index} className="muted">{warning}</li>
          ))}
        </ul>
        <div className="modal-actions">
          <button type="button" className="button-ghost" onClick={() => setImportWarnings(null)}>
            {t("close")}
          </button>
        </div>
      </Modal>
    </div>
  );
}
