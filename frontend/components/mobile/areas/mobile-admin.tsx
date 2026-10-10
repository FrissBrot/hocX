"use client";

import { usePathname, useRouter } from "next/navigation";
import type { Route } from "next";
import { ReactNode, useMemo, useState } from "react";
import { useLocale, useTranslations } from "next-intl";

import { MobileIcon } from "@/components/mobile/mobile-icons";
import { useMobileSession, useOpenMore } from "@/components/mobile/mobile-shell";
import {
  MobileActionSheet,
  MobileAvatar,
  MobileEmpty,
  MobileFab,
  MobileListRow,
  MobileSegmented,
  MobileSubHeader,
  MobileSwitch,
} from "@/components/mobile/mobile-ui";
import { dateParts, todayIso } from "@/components/mobile/mobile-utils";
import { getRoleOptions } from "@/components/admin/admin-tenant-settings-modal";
import { MfaAdminModal } from "@/components/security/mfa-admin-modal";
import { emptyUserForm, isUserFormValid, userFormToPayload, UserFormState } from "@/components/users/user-form-shared";
import { Modal } from "@/components/ui/modal";
import { SearchInput } from "@/components/ui/search-input";
import { useConfirm } from "@/contexts/confirm-context";
import { useToast } from "@/contexts/toast-context";
import { browserApiFetch } from "@/lib/api/client";
import { formatCycleName, getCycleYear } from "@/lib/utils/cycle";
import type { CycleConfigSummary, ShareLink, UserSummary } from "@/types/api";

// ── Zyklen ──────────────────────────────────────────────────────────────

export function MobileCycles({ initialConfigs }: { initialConfigs: CycleConfigSummary[] }) {
  const t = useTranslations("cycles");
  const tMobile = useTranslations("mobile");
  const openMore = useOpenMore();
  const [configs, setConfigs] = useState(initialConfigs);
  const [editing, setEditing] = useState<CycleConfigSummary | "new" | null>(null);
  const today = todayIso();

  return (
    <div className="mobile-page mobile-page-list">
      <MobileSubHeader title={t("pageTitle")} subtitle={t("pageDescription")} backLabel={tMobile("tabs.more")} onBack={openMore} />
      {configs.length > 0 ? (
        <div className="mobile-section">
          <div className="mobile-card mobile-list-card">
            {configs.map((config) => {
              const year = getCycleYear(today, config.reset_month, config.reset_day);
              return (
                <MobileListRow
                  key={config.id}
                  onClick={() => setEditing(config)}
                  label={
                    <span className="mobile-row-stack">
                      <span className="mobile-row-title">{config.name}</span>
                      <span className="mobile-row-meta">
                        {t("resetLabel", { date: `${config.reset_day}.${config.reset_month}.` })} · {t("currentLabel")} {formatCycleName(config.name_pattern, year)}
                      </span>
                    </span>
                  }
                />
              );
            })}
          </div>
        </div>
      ) : (
        <MobileEmpty title={t("noCycles")} />
      )}
      <MobileFab label={tMobile("cycles.fab")} onClick={() => setEditing("new")} />
      {editing ? (
        <CycleSheet
          config={editing === "new" ? null : editing}
          onClose={() => setEditing(null)}
          onSaved={(saved, created) => {
            setConfigs((list) => (created ? [...list, saved] : list.map((item) => (item.id === saved.id ? saved : item))).sort((a, b) => a.name.localeCompare(b.name)));
            setEditing(null);
          }}
          onDeleted={(id) => {
            setConfigs((list) => list.filter((item) => item.id !== id));
            setEditing(null);
          }}
        />
      ) : null}
    </div>
  );
}

function CycleSheet({
  config,
  onClose,
  onSaved,
  onDeleted,
}: {
  config: CycleConfigSummary | null;
  onClose: () => void;
  onSaved: (config: CycleConfigSummary, created: boolean) => void;
  onDeleted: (id: string) => void;
}) {
  const t = useTranslations("cycles");
  const tMobile = useTranslations("mobile");
  const locale = useLocale();
  const confirm = useConfirm();
  const showToast = useToast();
  const [name, setName] = useState(config?.name ?? "");
  const [month, setMonth] = useState(config?.reset_month ?? 7);
  const [day, setDay] = useState(config?.reset_day ?? 31);
  const [pattern, setPattern] = useState(config?.name_pattern ?? "");
  const [saving, setSaving] = useState(false);
  const preview = formatCycleName(pattern || null, getCycleYear(todayIso(), month, day));
  const months = useMemo(
    () => Array.from({ length: 12 }, (_, index) => new Intl.DateTimeFormat(locale, { month: "long" }).format(new Date(2026, index, 1))),
    [locale]
  );

  async function save() {
    if (!name.trim() || saving) return;
    setSaving(true);
    const body = JSON.stringify({ name: name.trim(), reset_month: month, reset_day: day, name_pattern: pattern.trim() || null });
    try {
      const saved = config
        ? await browserApiFetch<CycleConfigSummary>(`/api/cycle-configs/${config.id}`, { method: "PUT", body })
        : await browserApiFetch<CycleConfigSummary>("/api/cycle-configs", { method: "POST", body });
      onSaved(saved, !config);
    } catch (error) {
      showToast(error instanceof Error ? error.message : config ? t("saveFailed") : t("createFailed"), "error");
    } finally {
      setSaving(false);
    }
  }

  async function remove() {
    if (!config || !(await confirm({ message: t("deleteConfirm"), tone: "danger", confirmLabel: tMobile("common.delete") }))) return;
    try {
      await browserApiFetch(`/api/cycle-configs/${config.id}`, { method: "DELETE" });
      onDeleted(config.id);
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("deleteFailedGeneric"), "error");
    }
  }

  return (
    <Modal
      open
      size="sheet"
      title={config ? t("editCycleEyebrow") : t("newCycleEyebrow")}
      onClose={onClose}
      className="mobile-sheet"
      footer={
        <div className="modal-actions mobile-sheet-footer">
          {config ? (
            <button type="button" className="button-danger" onClick={() => void remove()}>
              {tMobile("common.delete")}
            </button>
          ) : (
            <button type="button" className="button-ghost" onClick={onClose}>
              {tMobile("common.cancel")}
            </button>
          )}
          <button type="button" className="button-primary" data-modal-save disabled={!name.trim() || saving} onClick={() => void save()}>
            {config ? tMobile("common.save") : t("createCycle")}
          </button>
        </div>
      }
    >
      <div className="grid mobile-sheet-body">
        <label className="field-stack">
          <span className="field-label">{t("nameLabel")}</span>
          <input value={name} onChange={(event) => setName(event.target.value)} placeholder={t("namePlaceholder")} />
          <span className="field-help">{t("nameHelp")}</span>
        </label>
        <div className="two-col">
          <label className="field-stack">
            <span className="field-label">{t("resetMonthLabel")}</span>
            <select value={month} onChange={(event) => setMonth(Number(event.target.value))}>
              {months.map((label, index) => (
                <option key={label} value={index + 1}>
                  {label}
                </option>
              ))}
            </select>
          </label>
          <label className="field-stack">
            <span className="field-label">{t("resetDayLabel")}</span>
            <input type="number" inputMode="numeric" min={1} max={31} value={day} onChange={(event) => setDay(Math.min(31, Math.max(1, Number(event.target.value) || 1)))} />
          </label>
        </div>
        <span className="field-help">{t("resetHelp")}</span>
        <label className="field-stack">
          <span className="field-label">{t("patternLabel")}</span>
          <input value={pattern} onChange={(event) => setPattern(event.target.value)} placeholder={t("patternPlaceholder")} />
          <span className="field-help">
            [cy] {t("patternHelpCy")} [cy_end] {t("patternHelpCyEnd")} {t("patternHelpPreviewLabel")} <strong>{preview}</strong>
          </span>
        </label>
        <p className="mobile-desktop-hint-text">{tMobile("cycles.deleteHint")}</p>
      </div>
    </Modal>
  );
}

// ── Benutzer ────────────────────────────────────────────────────────────

export function MobileUsers({ initialUsers }: { initialUsers: UserSummary[] }) {
  const t = useTranslations("users");
  const tAdmin = useTranslations("admin");
  const tMobile = useTranslations("mobile");
  const openMore = useOpenMore();
  const roleLabel = useMemo(() => new Map(getRoleOptions(tAdmin).map((role) => [role.code, role.label])), [tAdmin]);
  const [users, setUsers] = useState(initialUsers);
  const [tab, setTab] = useState<"active" | "nologin">("active");
  const [search, setSearch] = useState("");
  const [editing, setEditing] = useState<UserSummary | "new" | null>(null);
  const [enableFor, setEnableFor] = useState<UserSummary | null>(null);
  const [mfaFor, setMfaFor] = useState<UserSummary | null>(null);
  const active = users.filter((user) => user.login_enabled);
  const withoutLogin = users.filter((user) => !user.login_enabled);
  const needle = search.trim().toLowerCase();
  const visible = (tab === "active" ? active : withoutLogin).filter(
    (user) => !needle || `${user.display_name} ${user.email} ${roleLabel.get(user.role_code) ?? ""}`.toLowerCase().includes(needle)
  );

  return (
    <div className="mobile-page mobile-page-list">
      <MobileSubHeader title={t("pageTitle")} subtitle={t("ownAccessOnlyHint")} backLabel={tMobile("tabs.more")} onBack={openMore} />
      <div className="mobile-section">
        <MobileSegmented<"active" | "nologin">
          ariaLabel={t("pageTitle")}
          value={tab}
          onChange={setTab}
          options={[
            { value: "active", label: t("tabs.active", { count: active.length }) },
            { value: "nologin", label: t("tabs.participants", { count: withoutLogin.length }) },
          ]}
        />
        <SearchInput value={search} onChange={setSearch} placeholder={tab === "active" ? t("searchUsers") : t("searchParticipants")} />
      </div>
      {visible.length > 0 ? (
        <div className="mobile-section">
          <div className="mobile-card mobile-list-card">
            {visible.map((user) => (
              <MobileListRow
                key={user.id}
                onClick={() => (user.login_enabled ? setEditing(user) : setEnableFor(user))}
                leading={<MobileAvatar name={user.display_name} size="md" />}
                label={
                  <span className="mobile-row-stack">
                    <span className="mobile-row-title">{user.display_name}</span>
                    <span className="mobile-row-meta">{user.email}</span>
                  </span>
                }
                trailing={
                  user.login_enabled ? (
                    <span className={`mobile-role-pill mobile-role-pill-${user.role_code}`}>{roleLabel.get(user.role_code) ?? user.role_code}</span>
                  ) : (
                    <span className="mobile-text-link">{t("enableLogin")}</span>
                  )
                }
              />
            ))}
          </div>
        </div>
      ) : (
        <MobileEmpty title={t("emptyState.title")} hint={t("emptyState.description")} />
      )}
      <MobileFab label={tMobile("users.fab")} onClick={() => setEditing("new")} />

      {editing ? (
        <UserSheet
          user={editing === "new" ? null : editing}
          onClose={() => setEditing(null)}
          onMfa={(user) => {
            setEditing(null);
            setMfaFor(user);
          }}
          onSaved={(saved, created) => {
            setUsers((list) => (created ? [saved, ...list] : list.map((item) => (item.id === saved.id ? saved : item))));
            setEditing(null);
          }}
          onDeleted={(id) => {
            setUsers((list) => list.filter((item) => item.id !== id));
            setEditing(null);
          }}
        />
      ) : null}
      {enableFor ? (
        <EnableLoginSheet
          user={enableFor}
          onClose={() => setEnableFor(null)}
          onEnabled={(updated) => {
            setUsers((list) => [updated, ...list.filter((item) => item.id !== enableFor.id && item.id !== updated.id)]);
            setEnableFor(null);
          }}
        />
      ) : null}
      <MfaAdminModal
        open={!!mfaFor}
        onClose={() => setMfaFor(null)}
        title={mfaFor ? t("mfaTitle", { name: mfaFor.display_name }) : t("mfaTitleFallback")}
        loadPath={mfaFor ? `/api/users/${mfaFor.id}/mfa` : null}
        deletePathBase={mfaFor ? `/api/users/${mfaFor.id}/mfa/factors` : null}
      />
    </div>
  );
}

function UserSheet({
  user,
  onClose,
  onSaved,
  onDeleted,
  onMfa,
}: {
  user: UserSummary | null;
  onClose: () => void;
  onSaved: (user: UserSummary, created: boolean) => void;
  onDeleted: (id: string) => void;
  onMfa: (user: UserSummary) => void;
}) {
  const t = useTranslations("users");
  const tAdmin = useTranslations("admin");
  const tMobile = useTranslations("mobile");
  const confirm = useConfirm();
  const showToast = useToast();
  const session = useMobileSession();
  const roles = getRoleOptions(tAdmin).slice().reverse();
  const [form, setForm] = useState<UserFormState>(() =>
    user
      ? {
          id: user.id,
          first_name: user.first_name,
          last_name: user.last_name,
          display_name: user.display_name,
          email: user.email,
          password: "",
          preferred_language: user.preferred_language,
          is_active: user.is_active,
          login_enabled: user.login_enabled,
          is_participant_account: user.is_participant_account,
          tenant_id: user.tenant_id,
          role_code: user.role_code,
        }
      : emptyUserForm()
  );
  const [saving, setSaving] = useState(false);
  const update = (patch: Partial<UserFormState>) => setForm((current) => ({ ...current, ...patch }));
  const isSelf = !!user && user.id === session?.user?.id;

  async function save() {
    if (!isUserFormValid(form) || saving) return;
    setSaving(true);
    try {
      const body = JSON.stringify(userFormToPayload(form));
      const saved = user
        ? await browserApiFetch<UserSummary>(`/api/users/${user.id}`, { method: "PATCH", body })
        : await browserApiFetch<UserSummary>("/api/users", { method: "POST", body });
      showToast(user ? t("toasts.userSaved") : t("toasts.userCreated"), "success");
      onSaved(saved, !user);
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("toasts.userSaveFailed"), "error");
    } finally {
      setSaving(false);
    }
  }

  async function remove() {
    if (!user || !(await confirm({ message: t("toasts.deleteConfirm", { name: user.display_name }), tone: "danger", confirmLabel: t("delete") }))) return;
    try {
      await browserApiFetch(`/api/users/${user.id}`, { method: "DELETE" });
      showToast(t("toasts.userDeleted"), "success");
      onDeleted(user.id);
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("toasts.userDeleteFailed"), "error");
    }
  }

  return (
    <Modal
      open
      size="sheet"
      title={user ? user.display_name : t("createUserTitle")}
      description={t("userModalDescription")}
      onClose={onClose}
      className="mobile-sheet mobile-sheet-tall"
      headerActions={
        user ? (
          <button type="button" className="button-secondary" onClick={() => onMfa(user)}>
            {t("mfaButton")}
          </button>
        ) : null
      }
      footer={
        <div className="modal-actions mobile-sheet-footer">
          {user && !isSelf ? (
            <button type="button" className="button-danger" onClick={() => void remove()}>
              {t("delete")}
            </button>
          ) : (
            <button type="button" className="button-ghost" onClick={onClose}>
              {t("cancel")}
            </button>
          )}
          <button type="button" className="button-primary" data-modal-save disabled={!isUserFormValid(form) || saving} onClick={() => void save()}>
            {t("save")}
          </button>
        </div>
      }
    >
      <div className="grid mobile-sheet-body">
        <div className="two-col">
          <label className="field-stack">
            <span className="field-label">{t("firstName")}</span>
            <input value={form.first_name} onChange={(event) => update({ first_name: event.target.value })} />
          </label>
          <label className="field-stack">
            <span className="field-label">{t("lastName")}</span>
            <input value={form.last_name} onChange={(event) => update({ last_name: event.target.value })} />
          </label>
        </div>
        <label className="field-stack">
          <span className="field-label">{t("displayName")}</span>
          <input value={form.display_name} onChange={(event) => update({ display_name: event.target.value })} />
        </label>
        <label className="field-stack">
          <span className="field-label">{t("email")}</span>
          <input type="email" inputMode="email" value={form.email} onChange={(event) => update({ email: event.target.value })} />
        </label>
        <div className="field-stack">
          <span className="field-label">{t("role")}</span>
          <div className="mobile-card mobile-group-card">
            {roles.map((role) => (
              <button key={role.code} type="button" className="mobile-list-row" aria-pressed={form.role_code === role.code} onClick={() => update({ role_code: role.code })}>
                <span className={`mobile-check${form.role_code === role.code ? " mobile-check-on" : ""}`} aria-hidden="true">
                  {form.role_code === role.code ? <MobileIcon name="check" size={14} strokeWidth={3} /> : null}
                </span>
                <span className="mobile-row-stack">
                  <span className="mobile-row-title">{role.label}</span>
                  <span className="mobile-row-meta mobile-row-meta-wrap">{t(`roleDescriptions.${role.code}`)}</span>
                </span>
              </button>
            ))}
          </div>
        </div>
        <label className="field-stack">
          <span className="field-label">{user ? t("newPassword") : t("password")}</span>
          <input type="password" autoComplete="new-password" value={form.password} onChange={(event) => update({ password: event.target.value })} />
          <span className="field-help">{user ? t("passwordHelpEdit") : t("passwordHelpCreate")}</span>
        </label>
        <div className="mobile-card mobile-group-card">
          <button type="button" className="mobile-list-row" aria-pressed={form.is_active} onClick={() => update({ is_active: !form.is_active })}>
            <span className="mobile-list-row-label">{t("active")}</span>
            <MobileSwitch checked={form.is_active} />
          </button>
        </div>
        {form.is_participant_account ? <p className="mobile-desktop-hint-text">{t("participantAutoNote")}</p> : null}
      </div>
    </Modal>
  );
}

function EnableLoginSheet({ user, onClose, onEnabled }: { user: UserSummary; onClose: () => void; onEnabled: (user: UserSummary) => void }) {
  const t = useTranslations("users");
  const showToast = useToast();
  const [email, setEmail] = useState(user.email ?? "");
  const [password, setPassword] = useState("");
  const [saving, setSaving] = useState(false);
  const valid = email.trim().length > 0 && password.length >= 12;

  async function submit() {
    if (!valid || saving) return;
    setSaving(true);
    try {
      const updated = await browserApiFetch<UserSummary>(`/api/users/${user.id}`, {
        method: "PATCH",
        body: JSON.stringify({ email: email.trim(), password, login_enabled: true }),
      });
      showToast(t("toasts.loginEnabled"), "success");
      onEnabled(updated);
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("toasts.loginEnableFailed"), "error");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal
      open
      size="sheet"
      title={t("enableLoginForTitle", { name: user.display_name })}
      description={t("enableLoginDescription")}
      onClose={onClose}
      className="mobile-sheet"
      footer={
        <div className="modal-actions mobile-sheet-footer">
          <button type="button" className="button-ghost" onClick={onClose}>
            {t("cancel")}
          </button>
          <button type="button" className="button-primary" data-modal-save disabled={!valid || saving} onClick={() => void submit()}>
            {t("enableLogin")}
          </button>
        </div>
      }
    >
      <div className="grid mobile-sheet-body">
        <label className="field-stack">
          <span className="field-label">{t("email")}</span>
          <input type="email" inputMode="email" value={email} onChange={(event) => setEmail(event.target.value)} />
        </label>
        <label className="field-stack">
          <span className="field-label">{t("password")}</span>
          <input type="password" autoComplete="new-password" value={password} onChange={(event) => setPassword(event.target.value)} />
          <span className="field-help">{t("passwordHelpCreate")}</span>
        </label>
      </div>
    </Modal>
  );
}

// ── Geteilte Links ──────────────────────────────────────────────────────

export function MobileSharedLinks({ initialLinks }: { initialLinks: ShareLink[] }) {
  const t = useTranslations("sharedLinks");
  const tMobile = useTranslations("mobile");
  const locale = useLocale();
  const openMore = useOpenMore();
  const confirm = useConfirm();
  const showToast = useToast();
  const [links, setLinks] = useState(initialLinks);
  const [filter, setFilter] = useState<"active" | "all">("active");
  const [actionsFor, setActionsFor] = useState<ShareLink | null>(null);
  const visible = links.filter((link) => filter === "all" || link.status === "active");

  async function copy(link: ShareLink) {
    try {
      await navigator.clipboard.writeText(link.url);
      showToast(t("toasts.copied"), "success");
    } catch {
      showToast(t("toasts.copyFailed"), "error");
    }
  }

  async function revoke(link: ShareLink) {
    if (!(await confirm({ message: t("revokeConfirm", { name: link.name }), tone: "danger", confirmLabel: t("revokeConfirmLabel") }))) return;
    try {
      await browserApiFetch(`/api/share-links/${link.id}`, { method: "DELETE" });
      setLinks((list) => list.map((item) => (item.id === link.id ? { ...item, status: "revoked", revoked_at: new Date().toISOString() } : item)));
      showToast(t("toasts.revoked"), "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("toasts.revokeFailed"), "error");
    }
  }

  return (
    <div className="mobile-page mobile-page-list">
      <MobileSubHeader title={t("page.title")} subtitle={t("page.description")} backLabel={tMobile("tabs.more")} onBack={openMore} />
      <div className="mobile-section">
        <MobileSegmented<"active" | "all">
          ariaLabel={t("page.title")}
          value={filter}
          onChange={setFilter}
          options={[
            { value: "active", label: t("filterActive") },
            { value: "all", label: t("filterAll") },
          ]}
        />
      </div>
      {visible.length > 0 ? (
        <div className="mobile-section">
          <div className="mobile-card mobile-list-card">
            {visible.map((link) => (
              <MobileListRow
                key={link.id}
                onClick={() => setActionsFor(link)}
                chevron={false}
                leading={<MobileIcon name={link.album_name ? "people" : "document"} className="mobile-list-row-navicon" />}
                label={
                  <span className="mobile-row-stack">
                    <span className="mobile-row-title">{link.album_name ? t("table.albumScope", { name: link.album_name }) : link.name}</span>
                    <span className="mobile-row-meta">
                      {[
                        t("table.fileScope", { count: link.file_count }),
                        link.expires_at ? dateParts.dayMonth(link.expires_at.slice(0, 10), locale) : t("table.noExpiry"),
                        link.created_by_name,
                      ]
                        .filter(Boolean)
                        .join(" · ")}
                    </span>
                  </span>
                }
                trailing={link.status !== "active" ? <span className="mobile-status-pill">{t(`status.${link.status}`)}</span> : <MobileIcon name="more" />}
              />
            ))}
          </div>
        </div>
      ) : (
        <MobileEmpty title={links.length ? t("table.empty") : t("emptyTitle")} hint={links.length ? undefined : t("emptyDescription")} />
      )}
      {actionsFor ? (
        <MobileActionSheet
          title={actionsFor.album_name ? t("table.albumScope", { name: actionsFor.album_name }) : actionsFor.name}
          onClose={() => setActionsFor(null)}
          actions={[
            { label: t("table.copyLink"), onClick: () => void copy(actionsFor), disabled: actionsFor.status !== "active" },
            { label: t("table.revoke"), onClick: () => void revoke(actionsFor), danger: true, disabled: actionsFor.status !== "active" },
          ]}
        />
      ) : null}
    </div>
  );
}

// ── Mandant-Einstellungen ───────────────────────────────────────────────

const TENANT_TABS = [
  { href: "/tenant-settings", key: "general" },
  { href: "/tenant-settings/domains", key: "domains" },
  { href: "/tenant-settings/abo", key: "subscription" },
] as const;

/** Rahmen der drei Mandanten-Seiten: Kopf mit "‹ Mehr" und Segment statt Pill-Tabs. Inhalt sind
 * die bestehenden Formulare - schlank genug fuers Handy, Dialoge erscheinen als Sheets. */
export function MobileTenantSettings({ title, children }: { title: string; children: ReactNode }) {
  const tNav = useTranslations("nav");
  const tMobile = useTranslations("mobile");
  const router = useRouter();
  const pathname = usePathname();
  const openMore = useOpenMore();
  const active = TENANT_TABS.find((tab) => tab.href === pathname)?.key ?? "general";
  const labels = { general: tNav("general"), domains: tNav("domains"), subscription: tNav("subscriptionAndUsage") };
  return (
    <div className={`mobile-page${active === "domains" ? " mobile-page-list" : ""}`}>
      <MobileSubHeader title={title} backLabel={tMobile("tabs.more")} onBack={openMore} />
      <div className="mobile-section">
        <MobileSegmented<(typeof TENANT_TABS)[number]["key"]>
          ariaLabel={title}
          value={active}
          onChange={(key) => router.push(TENANT_TABS.find((tab) => tab.key === key)!.href as Route)}
          options={TENANT_TABS.map((tab) => ({ value: tab.key, label: labels[tab.key] }))}
        />
      </div>
      {children}
    </div>
  );
}
