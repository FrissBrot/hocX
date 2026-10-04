"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import { useLocale, useTranslations } from "next-intl";

import { AdminAvatar, BillingCycleToggle, formatPlanPrice, PlanBadge, PlanOption, planTones } from "@/components/admin/admin-plan-utils";
import { AdminTenantSettingsModal } from "@/components/admin/admin-tenant-settings-modal";
import { ActionMenu } from "@/components/ui/action-menu";
import { DataTable } from "@/components/ui/data-table";
import { FilterTabs } from "@/components/ui/filter-tabs";
import { Modal } from "@/components/ui/modal";
import { Pagination } from "@/components/ui/pagination";
import { SearchInput } from "@/components/ui/search-input";
import { browserApiFetch } from "@/lib/api/client";
import { useToast } from "@/contexts/toast-context";
import { useConfirm } from "@/contexts/confirm-context";
import { formatFileSize } from "@/lib/utils/format";
import { AdminPlan, AdminTenantCreate, AdminTenantPage, AdminTenantSummary } from "@/types/api";

type Props = {
  initialPage: AdminTenantPage;
  initialPlans: AdminPlan[];
  initialPlanFilter?: string;
};

const PAGE_SIZE = 50;

// Ab diesem Anteil wird der Speicherbalken in der Liste als Warnung eingefärbt.
const STORAGE_WARNING_RATIO = 0.85;

function slugify(value: string): string {
  return value
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

const emptyCreateForm: AdminTenantCreate & { slugTouched: boolean } = {
  name: "",
  public_slug: "",
  plan_code: null,
  billing_cycle: "monthly",
  slugTouched: false,
};

export function AdminTenantManagement({ initialPage, initialPlans, initialPlanFilter = "" }: Props) {
  const t = useTranslations("admin.tenants");
  const tPlans = useTranslations("admin.plans");
  const locale = useLocale();
  const showToast = useToast();
  const confirm = useConfirm();
  const [page, setPage] = useState(initialPage);
  const [offset, setOffset] = useState(0);
  const tenants = page.items;
  const [modalOpen, setModalOpen] = useState(false);
  const [createForm, setCreateForm] = useState(emptyCreateForm);
  const [createBusy, setCreateBusy] = useState(false);
  const [search, setSearch] = useState("");
  const [plans, setPlans] = useState<AdminPlan[]>(initialPlans);
  const [planFilter, setPlanFilter] = useState(initialPlanFilter);
  const [settingsModalOpen, setSettingsModalOpen] = useState(false);
  const [settingsTenant, setSettingsTenant] = useState<AdminTenantSummary | null>(null);
  const [cloneModalOpen, setCloneModalOpen] = useState(false);
  const [cloneTenant, setCloneTenant] = useState<AdminTenantSummary | null>(null);
  const [cloneName, setCloneName] = useState("");
  const [cloneMode, setCloneMode] = useState<"structure" | "full">("structure");
  const [cloneBusy, setCloneBusy] = useState(false);
  const [exportModalOpen, setExportModalOpen] = useState(false);
  const [exportTenant, setExportTenant] = useState<AdminTenantSummary | null>(null);
  const [exportScope, setExportScope] = useState<"structure" | "structure_lists" | "full" | "full_abgabebox">("structure");
  const [importModalOpen, setImportModalOpen] = useState(false);
  const [importName, setImportName] = useState("");
  const [importFile, setImportFile] = useState<File | null>(null);
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
      const q = query.trim();
      const result = await browserApiFetch<AdminTenantPage>(
        `/api/admin/tenants?limit=${PAGE_SIZE}&offset=${nextOffset}${q ? `&q=${encodeURIComponent(q)}` : ""}${plan ? `&plan=${encodeURIComponent(plan)}` : ""}`
      );
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

  // Debounced re-fetch from offset 0 whenever the search text changes - see the identical
  // pattern in admin-user-management.tsx.
  useEffect(() => {
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
        public_slug: createForm.public_slug?.trim() || null,
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

  function openSettings(tenant: AdminTenantSummary) {
    setSettingsTenant(tenant);
    setSettingsModalOpen(true);
  }

  function handleTenantSaved(updated: AdminTenantSummary) {
    const planChanged = page.items.find((tenant) => tenant.id === updated.id)?.plan_code !== updated.plan_code;
    setPage((current) => ({
      ...current,
      items: current.items.map((tenant) => (tenant.id === updated.id ? updated : tenant)),
    }));
    setSettingsTenant(updated);
    if (planChanged) void reloadPlans();
  }

  function openClone(tenant: AdminTenantSummary) {
    setCloneTenant(tenant);
    setCloneName(`${tenant.name} (Kopie)`);
    setCloneMode("structure");
    setCloneModalOpen(true);
  }

  async function submitClone(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!cloneTenant) return;
    setCloneBusy(true);
    try {
      await browserApiFetch<AdminTenantSummary>(`/api/admin/tenants/${cloneTenant.id}/clone`, {
        method: "POST",
        body: JSON.stringify({ new_name: cloneName, mode: cloneMode }),
      });
      await Promise.all([fetchPage(offset, search), reloadPlans()]);
      setCloneModalOpen(false);
      showToast(t("cloned"), "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("cloneFailed"), "error");
    } finally {
      setCloneBusy(false);
    }
  }

  function openExport(tenant: AdminTenantSummary) {
    setExportTenant(tenant);
    setExportScope("structure");
    setExportModalOpen(true);
  }

  async function submitExport(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!exportTenant) return;
    // Was a plain <a href> GET navigation (audit finding, 2026-08-25): with
    // SameSite=Lax cookies, a top-level navigation to that same URL from an external
    // page (an <a target=_top>, a redirect, ...) would have carried the logged-in
    // admin's session cookie and triggered a real export server-side, even though the
    // attacker page couldn't read the resulting file back. Fetching it here instead -
    // only reachable by JS running on this same origin, i.e. only by the admin actually
    // clicking this button - closes that off entirely; same blob-download pattern
    // downloadZip/downloadFile already use elsewhere in this codebase.
    try {
      const { browserApiBaseUrl } = await import("@/lib/api/client");
      const res = await fetch(`${browserApiBaseUrl}/api/admin/tenants/${exportTenant.id}/export?scope=${exportScope}`, {
        credentials: "include",
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const blob = await res.blob();
      const disposition = res.headers.get("content-disposition") ?? "";
      const filenameMatch = /filename="?([^";]+)"?/i.exec(disposition);
      const filename = filenameMatch?.[1] ?? `${exportTenant.name}-export.zip`;
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      a.click();
      URL.revokeObjectURL(url);
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("exportFailed"), "error");
      return;
    }
    setExportModalOpen(false);
  }

  async function deleteTenant(tenant: AdminTenantSummary) {
    const confirmed = await confirm({
      title: t("deleteConfirmTitle", { name: tenant.name }),
      message: t("deleteConfirmMessage", { participants: tenant.participant_count, users: tenant.user_count }),
      tone: "danger",
      confirmLabel: t("deletePermanently")
    });
    if (!confirmed) return;
    try {
      await browserApiFetch(`/api/admin/tenants/${tenant.id}`, { method: "DELETE" });
      // Deleting the last item on a page would strand the view past the new end - fall
      // back a page first if that's about to happen (changing offset re-triggers the load).
      if (tenants.length === 1 && offset > 0) {
        setOffset(offset - PAGE_SIZE);
      } else {
        await fetchPage(offset, search);
      }
      void reloadPlans();
      showToast(t("deleted"), "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("deleteFailed"), "error");
    }
  }

  function openImport() {
    setImportName("");
    setImportFile(null);
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
      const result = await browserApiFetch<{ tenant: AdminTenantSummary; warnings: string[] }>(
        "/api/admin/tenants/import",
        // Uploads/entpackt/importiert bis zu MAX_TENANT_IMPORT_UPLOAD_BYTES (2 GB, siehe
        // backend/app/api/routes/admin.py) - browserApiFetch's Default-Timeout von 15s reicht
        // dafuer bei weitem nicht, was zuvor als "Zeitueberschreitung beim Server" fehlschlug.
        { method: "POST", body: formData, signal: AbortSignal.timeout(600_000) }
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
      </article>

      <DataTable
        columns={[t("colImage"), t("colTenant"), t("colPlan"), t("colParticipants"), t("colUsers"), t("colStorage"), t("colCreatedAt"), ""]}
        emptyMessage={loading ? t("loading") : t("noTenantsFound")}
      >
        {visibleTenants.map((tenant) => {
          const plan = tenant.plan_code ? plansByCode.get(tenant.plan_code) : undefined;
          const usageRatio = tenant.storage_quota_bytes ? tenant.storage_used_bytes / tenant.storage_quota_bytes : 0;
          const storageState = usageRatio > 1 ? "over" : usageRatio >= STORAGE_WARNING_RATIO ? "warning" : "ok";
          return (
            <tr key={tenant.id} className="table-row-clickable" onClick={() => openSettings(tenant)}>
              <td>
                <AdminAvatar name={tenant.name} imageUrl={tenant.profile_image_url} toneKey={tenant.id} />
              </td>
              <td>
                <strong>{tenant.name}</strong>
                {tenant.public_slug ? <div className="muted admin-cell-sub">/{tenant.public_slug}</div> : null}
              </td>
              <td>
                {tenant.plan_code ? (
                  <PlanBadge name={tenant.plan_name ?? tenant.plan_code} tone={tones.get(tenant.plan_code) ?? "neutral"} />
                ) : (
                  <span className="muted">–</span>
                )}
                <div className="muted admin-cell-sub">{formatPlanPrice(plan, tenant.billing_cycle, tPlans)}</div>
              </td>
              <td className="admin-cell-number">{tenant.participant_count}</td>
              <td className="admin-cell-number">{tenant.user_count}</td>
              <td>
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
              </td>
              <td className="admin-cell-number">{new Date(tenant.created_at).toLocaleDateString(locale)}</td>
              <td onClick={(event) => event.stopPropagation()}>
                <ActionMenu
                  items={[
                    { label: t("settings"), onClick: () => openSettings(tenant) },
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
          <div className="two-col">
            <label className="field-stack">
              <span className="field-label">{t("tenantName")}</span>
              <input
                value={createForm.name}
                onChange={(event) => {
                  const name = event.target.value;
                  setCreateForm((current) => ({ ...current, name, public_slug: current.slugTouched ? current.public_slug : slugify(name) }));
                }}
                placeholder={t("tenantNamePlaceholder")}
                required
              />
            </label>
            <label className="field-stack">
              <span className="field-label">{t("publicSlug")}</span>
              <span className="admin-slug-input">
                <span className="admin-slug-prefix" aria-hidden="true">/</span>
                <input
                  value={createForm.public_slug ?? ""}
                  onChange={(event) =>
                    setCreateForm((current) => ({ ...current, public_slug: event.target.value.toLowerCase(), slugTouched: event.target.value !== "" }))
                  }
                  pattern="[a-z0-9-]+"
                  aria-label={t("publicSlug")}
                />
              </span>
            </label>
          </div>
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

      <AdminTenantSettingsModal
        open={settingsModalOpen}
        onClose={() => setSettingsModalOpen(false)}
        tenant={settingsTenant}
        onSaved={handleTenantSaved}
      />

      <Modal
        open={cloneModalOpen}
        onClose={() => setCloneModalOpen(false)}
        title={cloneTenant ? t("cloneTitleNamed", { name: cloneTenant.name }) : t("cloneTitle")}
        description={t("cloneDescription")}
      >
        <form className="grid" onSubmit={submitClone}>
          <label className="field-stack">
            <span className="field-label">{t("nameOfNewTenant")}</span>
            <input value={cloneName} onChange={(event) => setCloneName(event.target.value)} required />
          </label>
          <div className="field-stack">
            <span className="field-label">{t("scope")}</span>
            <label className="field-radio-option">
              <input
                type="radio"
                name="clone-mode"
                value="structure"
                checked={cloneMode === "structure"}
                onChange={() => setCloneMode("structure")}
              />
              <span>
                <strong>{t("cloneStructureOnlyTitle")}</strong>
                <div className="muted">{t("cloneStructureOnlyDescription")}</div>
              </span>
            </label>
            <label className="field-radio-option">
              <input
                type="radio"
                name="clone-mode"
                value="full"
                checked={cloneMode === "full"}
                onChange={() => setCloneMode("full")}
              />
              <span>
                <strong>{t("cloneFullTitle")}</strong>
                <div className="muted">{t("cloneFullDescription")}</div>
              </span>
            </label>
          </div>
          <div className="modal-actions">
            <button type="button" className="button-ghost" onClick={() => setCloneModalOpen(false)}>
              {t("cancel")}
            </button>
            <button type="submit" className="button-primary" disabled={cloneBusy}>
              {cloneBusy ? t("cloning") : t("clone")}
            </button>
          </div>
        </form>
      </Modal>

      <Modal
        open={exportModalOpen}
        onClose={() => setExportModalOpen(false)}
        title={exportTenant ? t("exportTitleNamed", { name: exportTenant.name }) : t("exportTitle")}
        description={t("exportDescription")}
      >
        <form className="grid" onSubmit={submitExport}>
          <div className="field-stack">
            <span className="field-label">{t("scope")}</span>
            <label className="field-radio-option">
              <input
                type="radio"
                name="export-scope"
                value="structure"
                checked={exportScope === "structure"}
                onChange={() => setExportScope("structure")}
              />
              <span>
                <strong>{t("exportStructureOnlyTitle")}</strong>
                <div className="muted">{t("exportStructureOnlyDescription")}</div>
              </span>
            </label>
            <label className="field-radio-option">
              <input
                type="radio"
                name="export-scope"
                value="structure_lists"
                checked={exportScope === "structure_lists"}
                onChange={() => setExportScope("structure_lists")}
              />
              <span>
                <strong>{t("exportStructureListsTitle")}</strong>
                <div className="muted">{t("exportStructureListsDescription")}</div>
              </span>
            </label>
            <label className="field-radio-option">
              <input
                type="radio"
                name="export-scope"
                value="full"
                checked={exportScope === "full"}
                onChange={() => setExportScope("full")}
              />
              <span>
                <strong>{t("exportFullTitle")}</strong>
                <div className="muted">{t("exportFullDescription")}</div>
              </span>
            </label>
            <label className="field-radio-option">
              <input
                type="radio"
                name="export-scope"
                value="full_abgabebox"
                checked={exportScope === "full_abgabebox"}
                onChange={() => setExportScope("full_abgabebox")}
              />
              <span>
                <strong>{t("exportFullAbgabeboxTitle")}</strong>
                <div className="muted">{t("exportFullAbgabeboxDescription")}</div>
              </span>
            </label>
          </div>
          <div className="modal-actions">
            <button type="button" className="button-ghost" onClick={() => setExportModalOpen(false)}>
              {t("cancel")}
            </button>
            <button type="submit" className="button-primary">
              {t("export")}
            </button>
          </div>
        </form>
      </Modal>

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
              accept=".zip"
              onChange={(event) => setImportFile(event.target.files?.[0] ?? null)}
              disabled={importBusy}
              required
            />
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
