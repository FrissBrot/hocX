"use client";

import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";

import { MfaAdminModal } from "@/components/security/mfa-admin-modal";
import { mfaState, rolesNeedMfa } from "@/components/users/access-helpers";
import { AccessPreviewModal } from "@/components/users/access-preview-modal";
import { EffectivePermissions, RoleChecklist } from "@/components/users/role-fields";
import { ActionMenu, type ActionMenuItem } from "@/components/ui/action-menu";
import { Badge } from "@/components/ui/badge";
import { DateInput } from "@/components/ui/date-input";
import { Modal, ModalSaveForm } from "@/components/ui/modal";
import { ProtectedExportModal } from "@/components/ui/protected-export-modal";
import { StatusBanner } from "@/components/ui/status-banner";
import { useConfirm } from "@/contexts/confirm-context";
import { useToast } from "@/contexts/toast-context";
import { browserApiFetch } from "@/lib/api/client";
import { apiErrorMessage } from "@/lib/api/error-message";
import { roleName } from "@/lib/permissions";
import { avatarTone, participantInitials } from "@/lib/utils/avatar";
import { formatDate, formatDateTime } from "@/lib/utils/format";
import type { FineTariffGroup, ParticipantInvite, ParticipantSummary, RoleRead, TemplateSummary, UserMfaOverview } from "@/types/api";

export type PersonPermissions = {
  // Login, Rollen, MFA: access.manage
  access: boolean;
  // Tarif sehen (finances.read) bzw. ändern (finances.manage)
  financeRead: boolean;
  financeManage: boolean;
  // Datenauskunft (data.export)
  dataExport: boolean;
};

type Props = {
  initialPerson: ParticipantSummary;
  templates: TemplateSummary[];
  initialTemplateIds: string[];
  roles: RoleRead[];
  tariffs: FineTariffGroup[];
  initialInvite: ParticipantInvite | null;
  initialMfa: UserMfaOverview | null;
  permissions: PersonPermissions;
  actorPermissions: string[];
  enabledFeatures: string[];
  ownUserId: string | null;
  tenantRequiresMfa: boolean;
};

type Draft = {
  first_name: string;
  last_name: string;
  display_name: string;
  email: string;
  joined_at: string;
  left_at: string;
  is_active: boolean;
  notify_without_login: boolean;
  template_ids: string[];
  tariff_id: string;
  role_ids: string[];
};

function draftOf(person: ParticipantSummary, templateIds: string[]): Draft {
  return {
    first_name: person.first_name ?? "",
    last_name: person.last_name ?? "",
    display_name: person.display_name,
    email: person.email ?? "",
    joined_at: person.joined_at ?? "",
    left_at: person.left_at ?? "",
    is_active: person.is_active,
    notify_without_login: Boolean(person.notify_without_login),
    template_ids: [...templateIds].sort(),
    tariff_id: person.tariff_id ?? "",
    role_ids: (person.roles ?? []).map((role) => role.id).sort(),
  };
}

const sameList = (a: string[], b: string[]) => a.length === b.length && [...a].sort().every((value, index) => value === [...b].sort()[index]);

/** Geänderte Felder des Entwurfs (für «N ungespeicherte Änderungen») */
function changedKeys(draft: Draft, saved: Draft): (keyof Draft)[] {
  return (Object.keys(draft) as (keyof Draft)[]).filter((key) => {
    const a = draft[key];
    const b = saved[key];
    return Array.isArray(a) && Array.isArray(b) ? !sameList(a, b) : a !== b;
  });
}

function todayIso(): string {
  return new Date().toISOString().slice(0, 10);
}

// Wie lange «✓ Gespeichert» in der Leiste stehen bleibt
const SAVED_NOTICE_MS = 2500;
// Ab so vielen Tarifen eine Liste statt Karten
const TARIFF_LIST_FROM = 5;

/** Personenseite /participants/[id] (Design «hocX Mitglied Profil»): Kopf mit Status, Abschnitte
 * als Karten mit Beschreibungsspalte (Stammdaten, Mitgliedschaft, Bussentarif, Login & Rollen),
 * Fusszeile mit Verlauf und Löschen. Felder sammeln Änderungen in einem Entwurf; die schwebende
 * Leiste unten speichert oder verwirft sie gemeinsam. Login-Aktionen (einladen, Passwort, MFA,
 * entziehen) wirken sofort. */
export function PersonPage({
  initialPerson, templates, initialTemplateIds, roles, tariffs, initialInvite, initialMfa,
  permissions, actorPermissions, enabledFeatures, ownUserId, tenantRequiresMfa,
}: Props) {
  const t = useTranslations("participants");
  const tUsers = useTranslations("users");
  const tNav = useTranslations("nav");
  const tSecurity = useTranslations("security");
  const router = useRouter();
  const showToast = useToast();
  const confirm = useConfirm();
  const [person, setPerson] = useState(initialPerson);
  const [savedTemplateIds, setSavedTemplateIds] = useState(initialTemplateIds);
  const [draft, setDraft] = useState<Draft>(() => draftOf(initialPerson, initialTemplateIds));
  const [saving, setSaving] = useState(false);
  const [justSaved, setJustSaved] = useState(false);
  const [invite, setInvite] = useState(initialInvite);
  const [inviteAvailable, setInviteAvailable] = useState(false);
  const [busy, setBusy] = useState(false);
  const [passwordOpen, setPasswordOpen] = useState(false);
  const [password, setPassword] = useState("");
  const [mfaOpen, setMfaOpen] = useState(false);
  const [mfa, setMfa] = useState(initialMfa);
  const [exportOpen, setExportOpen] = useState(false);
  const [previewOpen, setPreviewOpen] = useState(false);
  const loginSectionRef = useRef<HTMLElement>(null);
  const loginTitleRef = useRef<HTMLHeadingElement>(null);

  const saved = useMemo(() => draftOf(person, savedTemplateIds), [person, savedTemplateIds]);
  const changes = changedKeys(draft, saved);
  const dirty = changes.length > 0;
  const isSelf = ownUserId === person.id;
  const loginStatus = person.login_status ?? (person.login_enabled ? "active" : "none");
  const required = tenantRequiresMfa || rolesNeedMfa(roles, saved.role_ids);
  // «Ansehen als …» nur für Konten ohne mehr Rechte als man selbst (Backend prüft genauso, 403)
  const previewAllowed = roles
    .filter((role) => saved.role_ids.includes(role.id))
    .every((role) => role.permissions.every((key) => actorPermissions.includes(key)));
  const mfaStatus = mfaState(Boolean(mfa?.has_factors), Boolean(mfa?.required) || required);

  useEffect(() => {
    if (!permissions.access) return;
    let cancelled = false;
    browserApiFetch<{ enabled: boolean }>("/api/auth/password-reset/available")
      .then((result) => { if (!cancelled) setInviteAvailable(Boolean(result?.enabled)); })
      .catch(() => undefined);
    return () => { cancelled = true; };
  }, [permissions.access]);

  // Ungespeicherte Änderungen nicht stillschweigend verlieren (Tab schliessen, neu laden)
  useEffect(() => {
    if (!dirty) return;
    const warn = (event: BeforeUnloadEvent) => { event.preventDefault(); };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  // «✓ Gespeichert» kurz zeigen, dann verschwindet die Leiste
  useEffect(() => {
    if (!justSaved) return;
    const timer = window.setTimeout(() => setJustSaved(false), SAVED_NOTICE_MS);
    return () => window.clearTimeout(timer);
  }, [justSaved]);

  const set = <K extends keyof Draft>(key: K, value: Draft[K]) => {
    setJustSaved(false);
    setDraft((current) => ({ ...current, [key]: value }));
  };
  const errorText = (error: unknown, fallback: string) => apiErrorMessage(error, tSecurity, "apiErrors", fallback);

  const blocker: "displayName" | "dates" | "loginEmail" | null = !draft.display_name.trim()
    ? "displayName"
    : draft.joined_at && draft.left_at && draft.left_at < draft.joined_at
      ? "dates"
      : person.login_enabled && !draft.email.trim() ? "loginEmail" : null;

  async function save() {
    if (!dirty || blocker || saving) return;
    setSaving(true);
    try {
      const fields: Record<string, unknown> = {};
      const plain = ["first_name", "last_name", "display_name", "email", "joined_at", "left_at"] as const;
      for (const key of plain) {
        if (draft[key] !== saved[key]) fields[key] = draft[key].trim() || (key === "display_name" ? draft[key] : null);
      }
      if (draft.is_active !== saved.is_active) fields.is_active = draft.is_active;
      if (draft.notify_without_login !== saved.notify_without_login) fields.notify_without_login = draft.notify_without_login;
      if (permissions.access && !sameList(draft.role_ids, saved.role_ids)) fields.role_ids = draft.role_ids;
      if (Object.keys(fields).length) {
        await browserApiFetch<ParticipantSummary>(`/api/participants/${person.id}`, { method: "PATCH", body: JSON.stringify(fields) });
      }
      if (!sameList(draft.template_ids, saved.template_ids)) {
        await browserApiFetch(`/api/participants/${person.id}/templates`, { method: "PUT", body: JSON.stringify({ template_ids: draft.template_ids }) });
        setSavedTemplateIds(draft.template_ids);
      }
      if (permissions.financeManage && draft.tariff_id !== saved.tariff_id) {
        await browserApiFetch(`/api/todo-fines/tariff-members/${person.id}`, {
          method: "PUT",
          body: JSON.stringify({ tariff_group_id: draft.tariff_id || null }),
        });
      }
      const updated = await browserApiFetch<ParticipantSummary>(`/api/participants/${person.id}`);
      setPerson(updated);
      setDraft(draftOf(updated, draft.template_ids));
      setJustSaved(true);
    } catch (error) {
      showToast(errorText(error, t("toasts.saveFailed")), "error");
    } finally {
      setSaving(false);
    }
  }

  async function reload() {
    const updated = await browserApiFetch<ParticipantSummary>(`/api/participants/${person.id}`);
    setPerson(updated);
    // Nur Login-Status/Rollen übernehmen, laufende Eingaben im Entwurf bleiben
    setDraft((current) => ({ ...current, role_ids: dirty ? current.role_ids : (updated.roles ?? []).map((role) => role.id).sort() }));
  }

  async function sendInvite() {
    setBusy(true);
    try {
      const created = await browserApiFetch<ParticipantInvite>(`/api/participants/${person.id}/invite`, { method: "POST" });
      setInvite(created);
      await reload();
      showToast(t("invite.sentToast", { email: person.email ?? "" }), "success");
    } catch (error) {
      showToast(errorText(error, t("invite.failed")), "error");
    } finally {
      setBusy(false);
    }
  }

  async function revokeInvite() {
    const ok = await confirm({ message: t("invite.revokeConfirm", { name: person.display_name }), tone: "danger", confirmLabel: t("invite.revoke") });
    if (!ok) return;
    setBusy(true);
    try {
      await browserApiFetch(`/api/participants/${person.id}/invite`, { method: "DELETE" });
      setInvite(null);
      await reload();
      showToast(t("invite.revokedToast"), "success");
    } catch (error) {
      showToast(errorText(error, t("invite.failed")), "error");
    } finally {
      setBusy(false);
    }
  }

  async function setLoginPassword(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (password.length < 12) return;
    setBusy(true);
    try {
      await browserApiFetch(`/api/participants/${person.id}`, {
        method: "PATCH",
        body: JSON.stringify({ login_enabled: true, password }),
      });
      setPasswordOpen(false);
      setPassword("");
      await reload();
      showToast(tUsers("toasts.loginEnabled"), "success");
    } catch (error) {
      showToast(errorText(error, tUsers("toasts.loginEnableFailed")), "error");
    } finally {
      setBusy(false);
    }
  }

  async function revokeLogin() {
    const ok = await confirm({
      title: tUsers("revokeLogin.confirmTitle", { name: person.display_name }),
      message: tUsers("revokeLogin.confirmMessage", { name: person.display_name }),
      tone: "danger",
      confirmLabel: tUsers("revokeLogin.action"),
    });
    if (!ok) return;
    setBusy(true);
    try {
      await browserApiFetch(`/api/participants/${person.id}`, { method: "PATCH", body: JSON.stringify({ login_enabled: false }) });
      await reload();
      showToast(tUsers("revokeLogin.done", { name: person.display_name }), "success");
    } catch (error) {
      showToast(errorText(error, tUsers("revokeLogin.failed")), "error");
    } finally {
      setBusy(false);
    }
  }

  async function deletePerson() {
    const ok = await confirm({
      title: t("deleteDialog.title", { name: person.display_name }),
      message: person.login_enabled ? t("deleteDialog.messageWithLogin") : t("deleteDialog.message"),
      tone: "danger",
      confirmLabel: t("deleteDialog.confirm"),
    });
    if (!ok) return;
    try {
      await browserApiFetch(`/api/participants/${person.id}`, { method: "DELETE" });
      showToast(t("toasts.deletedSingle", { name: person.display_name }), "success");
      router.push("/participants");
    } catch (error) {
      showToast(errorText(error, t("toasts.deleteFailed")), "error");
    }
  }

  async function closeMfa() {
    setMfaOpen(false);
    try {
      setMfa(await browserApiFetch<UserMfaOverview>(`/api/users/${person.id}/mfa`));
    } catch {
      // Status bleibt wie zuletzt geladen
    }
  }

  function showLoginSection() {
    loginSectionRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    loginTitleRef.current?.focus({ preventScroll: true });
  }

  const defaultTariff = tariffs.find((tariff) => tariff.is_default);
  const tariffLabel = (id: string) =>
    id ? tariffs.find((tariff) => tariff.id === id)?.name ?? "–" : t("person.tariffStandard", { name: defaultTariff?.name ?? "–" });
  // Der Standardtarif steht im Entwurf als "" (keine eigene Zuordnung)
  const tariffValue = (tariff: FineTariffGroup) => (tariff.is_default ? "" : tariff.id);
  const tariffSelected = (tariff: FineTariffGroup) =>
    draft.tariff_id === tariff.id || (tariff.is_default && draft.tariff_id === "");
  const today = todayIso();
  const hasLeft = Boolean(person.left_at && person.left_at < today);
  const emailChanged = draft.email.trim() !== (person.email ?? "");
  const canInvite = inviteAvailable && Boolean(person.email) && person.is_active && !hasLeft && !emailChanged;
  // Mit aktivem Login ist die E-Mail zugleich die Login-Adresse (Backend verlangt sie dann)
  const hasLoginAddress = Boolean(person.login_enabled);
  const composedName = [draft.first_name.trim(), draft.last_name.trim()].filter(Boolean).join(" ");
  const selectedTemplates = draft.template_ids.filter((id) => templates.some((template) => template.id === id)).length;

  const status = person.left_at
    ? { variant: "warning" as const, label: t("person.status.left", { date: formatDate(person.left_at) }) }
    : person.is_active
      ? { variant: "success" as const, label: t("person.status.active") }
      : { variant: "neutral" as const, label: t("person.status.inactive") };

  const menuItems: ActionMenuItem[] = [];
  if (permissions.access && previewAllowed && loginStatus !== "none") {
    menuItems.push({ label: t("person.previewAction"), onClick: () => setPreviewOpen(true) });
  }
  if (permissions.dataExport && !isSelf) {
    menuItems.push({ label: t("personalData.action"), onClick: () => setExportOpen(true) });
  }
  if (loginStatus === "active" && permissions.access && !isSelf) {
    menuItems.push({ label: tUsers("revokeLogin.action"), onClick: () => void revokeLogin(), danger: true });
  }

  const tariffOptions = defaultTariff
    ? [defaultTariff, ...tariffs.filter((tariff) => !tariff.is_default)]
    : tariffs;

  return (
    <div className="grid person-page">
      <Link href="/participants" className="person-back-link">{t("person.back")}</Link>

      <header className="person-hero">
        <span className={`participant-avatar person-hero-avatar participant-avatar-tone-${avatarTone(person.id)}`} aria-hidden="true">
          {participantInitials(person)}
        </span>
        <div className="person-hero-text">
          <div className="person-hero-title-row">
            <h1 className="person-hero-title">{person.display_name}</h1>
            <Badge variant={status.variant} dot>{status.label}</Badge>
          </div>
          <p className="person-hero-meta">
            <span>{person.joined_at ? t("person.memberSince", { date: formatDate(person.joined_at) }) : t("membership.noJoinDate")}</span>
            {permissions.financeRead && tariffs.length ? (
              <span>{t("person.tariffMeta", { tariff: tariffLabel(saved.tariff_id) })}</span>
            ) : null}
          </p>
        </div>
        <div className="person-hero-actions">
          <button type="button" className="button-secondary" onClick={showLoginSection}>{t("person.loginAndRole")}</button>
          {menuItems.length ? <ActionMenu items={menuItems} ariaLabel={t("person.moreActions")} /> : null}
        </div>
      </header>

      <section className="card section-card person-card" aria-labelledby="person-master">
        <div className="person-card-intro">
          <h2 id="person-master" className="person-section-title">{t("person.sections.master")}</h2>
          <p className="person-card-description">{t("person.descriptions.master")}</p>
        </div>
        <div className="person-card-body">
          <div className="two-col">
            <label className="field-stack">
              <span className="field-label">{t("editModal.firstName")}</span>
              <input value={draft.first_name} onChange={(event) => set("first_name", event.target.value)} />
            </label>
            <label className="field-stack">
              <span className="field-label">{t("editModal.lastName")}</span>
              <input value={draft.last_name} onChange={(event) => set("last_name", event.target.value)} />
            </label>
          </div>
          <div className="field-stack">
            <div className="person-field-head">
              <label htmlFor="person-display-name" className="field-label">{t("editModal.displayName")}</label>
              <button type="button" className="person-inline-action" disabled={!composedName || composedName === draft.display_name}
                onClick={() => set("display_name", composedName)}>
                {t("person.displayNameFromParts")}
              </button>
            </div>
            <input id="person-display-name" value={draft.display_name} onChange={(event) => set("display_name", event.target.value)} required />
          </div>
          <div className="field-stack">
            <div className="person-field-head">
              <label htmlFor="person-email" className="field-label">{t("editModal.email")}</label>
              {hasLoginAddress ? <Badge variant="info">{t("person.loginBadge")}</Badge> : null}
            </div>
            <input id="person-email" type="email" value={draft.email} onChange={(event) => set("email", event.target.value)} />
            {hasLoginAddress && emailChanged ? (
              <span className="person-email-change" role="status">
                {draft.email.trim() ? t("person.emailLoginChanged", { email: person.email ?? "" }) : t("person.blockers.loginEmail")}
              </span>
            ) : (
              <span className="field-help">{hasLoginAddress ? t("person.emailLoginHelp") : t("person.emailHelp")}</span>
            )}
          </div>
          {loginStatus !== "active" ? (
            <label className="checkbox-line person-checkbox-line">
              <input type="checkbox" checked={draft.notify_without_login} disabled={!draft.email.trim()}
                onChange={(event) => set("notify_without_login", event.target.checked)} />
              <span className="person-check-text">
                <span>{t("editModal.notifyWithoutLogin")}</span>
                <span className="field-help">{draft.email.trim() ? t("editModal.notifyWithoutLoginHint") : t("editModal.notifyWithoutLoginNeedsEmail")}</span>
              </span>
            </label>
          ) : null}
        </div>
      </section>

      <section className="card section-card person-card" aria-labelledby="person-membership">
        <div className="person-card-intro">
          <h2 id="person-membership" className="person-section-title">{t("person.sections.membership")}</h2>
          <p className="person-card-description">{t("person.descriptions.membership")}</p>
        </div>
        <div className="person-card-body">
          <label className="profile-toggle">
            <span className="profile-toggle-text">
              <span>{t("person.activeMember")}</span>
              <span className="field-help">{t("person.activeMemberHelp")}</span>
            </span>
            <input type="checkbox" role="switch" checked={draft.is_active} onChange={(event) => set("is_active", event.target.checked)} />
            <span className="album-picker-switch-track" aria-hidden="true" />
          </label>
          <div className="two-col">
            <label className="field-stack">
              <span className="field-label">{t("editModal.joinedAt")}</span>
              <DateInput value={draft.joined_at} onChange={(value) => set("joined_at", value)} />
            </label>
            <label className="field-stack">
              <span className="field-label">{t("editModal.leftAt")}</span>
              <DateInput value={draft.left_at} min={draft.joined_at || undefined} onChange={(value) => set("left_at", value)} />
            </label>
          </div>
          <span className="field-help">{t("person.membershipHelp")}</span>
          <div className="field-stack" role="group" aria-labelledby="person-templates-label">
            <div className="person-field-head">
              <span id="person-templates-label" className="field-label">{t("person.attendanceLists")}</span>
              {templates.length ? (
                <span className="person-counter">{t("person.attendanceCount", { selected: selectedTemplates, total: templates.length })}</span>
              ) : null}
            </div>
            {templates.length ? (
              <div className="person-checklist">
                {templates.map((template) => {
                  const checked = draft.template_ids.includes(template.id);
                  return (
                    <label key={template.id} className={`person-check-row${checked ? " person-check-row-active" : ""}`}>
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={(event) => set("template_ids", (event.target.checked
                          ? [...new Set([...draft.template_ids, template.id])]
                          : draft.template_ids.filter((id) => id !== template.id)).sort())}
                      />
                      <span className="person-check-text">
                        <strong>{template.name}</strong>
                        {template.description ? <span className="muted">{template.description}</span> : null}
                      </span>
                    </label>
                  );
                })}
              </div>
            ) : (
              <span className="muted">{t("person.noTemplates")}</span>
            )}
          </div>
        </div>
      </section>

      {permissions.financeRead ? (
        <section className="card section-card person-card" aria-labelledby="person-tariff">
          <div className="person-card-intro">
            <h2 id="person-tariff" className="person-section-title">{t("person.sections.tariff")}</h2>
            <p className="person-card-description">{t("person.descriptions.tariff")}</p>
            {permissions.financeManage ? <Link href="/fine-settings" className="person-section-link">{t("person.manageTariffs")}</Link> : null}
          </div>
          <div className="person-card-body">
            {tariffs.length === 0 ? (
              <p className="muted">{t("person.noTariffs")}</p>
            ) : !permissions.financeManage || tariffs.length === 1 ? (
              <div className="person-tariff-tile">
                <strong>{tariffLabel(saved.tariff_id)}</strong>
                <span className="field-help">
                  {!permissions.financeManage ? t("person.tariffReadOnly", { tariff: tariffLabel(saved.tariff_id) }) : t("person.tariffSingle")}
                </span>
              </div>
            ) : (
              <div
                className={tariffs.length >= TARIFF_LIST_FROM ? "person-checklist" : "person-tariff-cards"}
                role="radiogroup"
                aria-labelledby="person-tariff"
              >
                {tariffOptions.map((tariff) => {
                  const selected = tariffSelected(tariff);
                  const list = tariffs.length >= TARIFF_LIST_FROM;
                  const base = list ? "person-check-row" : "person-tariff-card";
                  return (
                    <label key={tariff.id} className={`${base}${selected ? ` ${base}-active` : ""}`}>
                      <input type="radio" name="person-tariff" checked={selected} onChange={() => set("tariff_id", tariffValue(tariff))} />
                      <span className="person-check-text">
                        <strong>{tariff.name}</strong>
                        <span className="muted">
                          {tariff.is_default ? t("person.tariffDefaultHint") : t("person.tariffMembers", { count: tariff.member_count })}
                        </span>
                      </span>
                    </label>
                  );
                })}
              </div>
            )}
          </div>
        </section>
      ) : null}

      <section ref={loginSectionRef} className="card section-card person-card" aria-labelledby="person-login">
        <div className="person-card-intro">
          <h2 id="person-login" ref={loginTitleRef} tabIndex={-1} className="person-section-title">{t("person.sections.login")}</h2>
          <p className="person-card-description">{t("person.descriptions.login")}</p>
          {permissions.access ? <Link href="/users/roles" className="person-section-link">{t("person.rolesExplained")}</Link> : null}
        </div>
        <div className="person-card-body">
          <div className="person-field-head">
            <span className="field-label">{t("person.loginLabel")}</span>
            <Badge variant={loginStatus === "active" ? "success" : loginStatus === "invited" ? "info" : "neutral"}>
              {t(`person.loginStatus.${loginStatus}`)}
            </Badge>
          </div>

          {loginStatus === "none" ? (
            <>
              <p className="muted">{t("person.noLogin")}</p>
              {permissions.access ? (
                <div className="table-actions table-actions-start">
                  <button type="button" className="button-secondary" disabled={busy || !canInvite} onClick={() => void sendInvite()}>
                    {t("invite.send")}
                  </button>
                  <button type="button" className="button-secondary button-ghost" disabled={busy || !person.email || emailChanged || !person.is_active || hasLeft}
                    onClick={() => { setPassword(""); setPasswordOpen(true); }}>
                    {t("person.setPassword")}
                  </button>
                </div>
              ) : null}
              {permissions.access && !inviteAvailable ? <span className="field-help">{t("invite.mailOff")}</span> : null}
              {permissions.access && emailChanged ? <span className="field-help">{t("invite.saveEmailFirst")}</span> : null}
              {permissions.access && !person.email && !emailChanged ? <span className="field-help">{t("invite.needsEmail")}</span> : null}
            </>
          ) : null}

          {loginStatus === "invited" ? (
            <>
              <p className="muted">
                {invite?.sent_at
                  ? t("invite.pendingSent", { sent: formatDateTime(invite.sent_at), expires: formatDateTime(invite.expires_at ?? "") })
                  : t("invite.pendingQueued")}
              </p>
              {permissions.access ? (
                <div className="table-actions table-actions-start">
                  <button type="button" className="button-secondary" disabled={busy || !canInvite} onClick={() => void sendInvite()}>{t("invite.resend")}</button>
                  <button type="button" className="button-ghost" disabled={busy} onClick={() => void revokeInvite()}>{t("invite.revoke")}</button>
                </div>
              ) : null}
            </>
          ) : null}

          {loginStatus === "active" && hasLeft ? <StatusBanner tone="warning" message={t("membership.loginBlocked")} /> : null}

          {permissions.access ? (
            <div className="two-col">
              <RoleChecklist roles={roles} value={draft.role_ids} actorPermissions={actorPermissions} onChange={(ids) => set("role_ids", [...ids].sort())} />
              <EffectivePermissions roles={roles} roleIds={draft.role_ids} enabledFeatures={enabledFeatures} />
            </div>
          ) : (
            <div className="field-stack">
              <span className="field-label">{t("person.roles")}</span>
              <span className="access-role-chips">
                {(person.roles ?? []).map((role) => <Badge key={role.id} variant="neutral">{roleName(role, tNav)}</Badge>)}
              </span>
            </div>
          )}

          {permissions.access ? (
            <div className="person-login-row">
              <span className="field-help">
                {!previewAllowed ? t("person.previewNotAllowed") : !sameList(draft.role_ids, saved.role_ids) ? t("person.previewSavedOnly") : t("person.previewHelp")}
              </span>
              <button type="button" className="button-secondary" disabled={!previewAllowed} onClick={() => setPreviewOpen(true)}>
                {t("person.previewAction")}
              </button>
            </div>
          ) : null}

          {loginStatus === "active" && permissions.access ? (
            <div className="person-login-row">
              <div className="field-stack">
                <span className="field-label">{t("person.mfa")}</span>
                {mfa ? (
                  <Badge variant={mfaStatus === "active" ? "success" : mfaStatus === "missing" ? "warning" : "neutral"} dot>
                    {tUsers(`access.mfa.${mfaStatus}`)}
                  </Badge>
                ) : <span className="muted">–</span>}
              </div>
              {mfa ? <button type="button" className="button-secondary" onClick={() => setMfaOpen(true)}>{tUsers("mfaButton")}</button> : null}
            </div>
          ) : null}

          {loginStatus === "active" && permissions.access && !isSelf ? (
            <div className="person-login-row">
              <span className="field-help">{t("person.revokeHelp")}</span>
              <button type="button" className="button-secondary button-danger" disabled={busy} onClick={() => void revokeLogin()}>
                {tUsers("revokeLogin.action")}
              </button>
            </div>
          ) : null}
        </div>
      </section>

      <footer className="person-footer">
        <span className="person-footer-meta">
          {person.created_at ? <span>{t("person.createdAt", { date: formatDate(person.created_at) })}</span> : null}
          {person.updated_at ? <span>{t("person.updatedAt", { date: formatDate(person.updated_at) })}</span> : null}
        </span>
        {!isSelf ? (
          <button type="button" className="button-secondary button-danger" onClick={() => void deletePerson()}>{t("person.deleteMember")}</button>
        ) : null}
      </footer>

      {dirty || justSaved ? (
        <div className={`person-save-bar${dirty ? "" : " person-save-bar-done"}`} role="region" aria-label={dirty ? t("person.unsaved") : t("person.saved")}>
          {dirty ? (
            <>
              <span className="person-save-bar-text">
                {blocker ? t(`person.blockers.${blocker}`) : t("person.unsavedCount", { count: changes.length })}
              </span>
              <button type="button" className="button-ghost" disabled={saving} onClick={() => setDraft(saved)}>{t("person.discard")}</button>
              <button type="button" className="button-primary" disabled={saving || blocker !== null} onClick={() => void save()}>{t("editModal.save")}</button>
            </>
          ) : (
            <span className="person-save-bar-text" role="status">{t("person.savedCheck")}</span>
          )}
        </div>
      ) : null}

      <Modal open={passwordOpen} onClose={() => setPasswordOpen(false)} title={tUsers("enableLoginForTitle", { name: person.display_name })} description={t("person.passwordDescription")}>
        <ModalSaveForm className="grid" onSubmit={setLoginPassword}>
          <label className="field-stack">
            <span className="field-label">{tUsers("password")}</span>
            <input type="password" autoComplete="new-password" value={password} minLength={12} onChange={(event) => setPassword(event.target.value)} />
            <span className="field-help">{tUsers("passwordHelpSet")}</span>
          </label>
          <div className="modal-actions">
            <button type="button" className="button-ghost" onClick={() => setPasswordOpen(false)}>{tUsers("cancel")}</button>
            <button data-modal-save type="submit" className="button-primary" disabled={busy || password.length < 12}>{tUsers("enableLogin")}</button>
          </div>
        </ModalSaveForm>
      </Modal>

      <MfaAdminModal
        open={mfaOpen}
        onClose={() => void closeMfa()}
        title={tUsers("mfaTitle", { name: person.display_name })}
        loadPath={mfaOpen ? `/api/users/${person.id}/mfa` : null}
        deletePathBase={mfaOpen ? `/api/users/${person.id}/mfa/factors` : null}
      />

      {previewOpen ? (
        <AccessPreviewModal open onClose={() => setPreviewOpen(false)} userId={person.id} name={person.display_name} />
      ) : null}

      {exportOpen ? (
        <ProtectedExportModal
          open
          title={t("personalData.title", { name: person.display_name })}
          description={t("personalData.description")}
          path={`/api/participants/${person.id}/personal-data`}
          fallbackFilename="hocx-data.zip"
          onClose={() => setExportOpen(false)}
        />
      ) : null}
    </div>
  );
}
