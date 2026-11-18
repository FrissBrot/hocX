"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";

import { MfaAdminModal } from "@/components/security/mfa-admin-modal";
import { mfaState, rolesNeedMfa } from "@/components/users/access-helpers";
import { AccessPreviewModal } from "@/components/users/access-preview-modal";
import { EffectivePermissions, RoleChecklist } from "@/components/users/role-fields";
import { Badge } from "@/components/ui/badge";
import { DateInput } from "@/components/ui/date-input";
import { Modal, ModalSaveForm } from "@/components/ui/modal";
import { ProtectedExportModal } from "@/components/ui/protected-export-modal";
import { Select } from "@/components/ui/select";
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

function todayIso(): string {
  return new Date().toISOString().slice(0, 10);
}

/** Personenseite /participants/[id] (Konzept «Personen an einem Ort»): alles zu einer Person an
 * einem Ort - Stammdaten, Mitgliedschaft, Bussentarif, Login & Rollen, weitere Aktionen. Felder
 * sammeln Änderungen in einem Entwurf; die Leiste unten speichert oder verwirft sie gemeinsam.
 * Login-Aktionen (einladen, Passwort, MFA, entziehen) wirken sofort, wie bisher. */
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
  const [invite, setInvite] = useState(initialInvite);
  const [inviteAvailable, setInviteAvailable] = useState(false);
  const [busy, setBusy] = useState(false);
  const [passwordOpen, setPasswordOpen] = useState(false);
  const [password, setPassword] = useState("");
  const [mfaOpen, setMfaOpen] = useState(false);
  const [mfa, setMfa] = useState(initialMfa);
  const [exportOpen, setExportOpen] = useState(false);
  const [previewOpen, setPreviewOpen] = useState(false);

  const saved = useMemo(() => draftOf(person, savedTemplateIds), [person, savedTemplateIds]);
  const dirty = JSON.stringify(draft) !== JSON.stringify(saved);
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

  const set = <K extends keyof Draft>(key: K, value: Draft[K]) => setDraft((current) => ({ ...current, [key]: value }));
  const errorText = (error: unknown, fallback: string) => apiErrorMessage(error, tSecurity, "apiErrors", fallback);

  const blocker: "displayName" | "dates" | null = !draft.display_name.trim()
    ? "displayName"
    : draft.joined_at && draft.left_at && draft.left_at < draft.joined_at ? "dates" : null;

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
      let updated = person;
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
      updated = await browserApiFetch<ParticipantSummary>(`/api/participants/${person.id}`);
      setPerson(updated);
      setDraft(draftOf(updated, draft.template_ids));
      showToast(t("person.saved"), "success");
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

  const defaultTariff = tariffs.find((tariff) => tariff.is_default);
  const tariffLabel = (id: string) =>
    id ? tariffs.find((tariff) => tariff.id === id)?.name ?? "–" : t("person.tariffStandard", { name: defaultTariff?.name ?? "–" });
  const today = todayIso();
  const hasLeft = Boolean(person.left_at && person.left_at < today);
  const emailChanged = draft.email.trim() !== (person.email ?? "");
  const canInvite = inviteAvailable && Boolean(person.email) && person.is_active && !hasLeft && !emailChanged;

  return (
    <div className="grid person-page">
      <div className="page-header">
        <div className="participant-name-cell">
          <span className={`participant-avatar participant-avatar-tone-${avatarTone(person.id)}`} aria-hidden="true">
            {participantInitials(person)}
          </span>
          <div className="participant-name-text">
            <Link href="/participants" className="person-back-link">{t("person.back")}</Link>
            <h1 className="page-title">{person.display_name}</h1>
            <span className="participant-name-sub">
              {person.left_at && hasLeft
                ? t("membership.leftSince", { date: formatDate(person.left_at) })
                : person.joined_at ? t("membership.memberSince", { year: person.joined_at.slice(0, 4) }) : t("membership.noJoinDate")}
            </span>
          </div>
        </div>
      </div>

      <section className="section-card person-section" aria-labelledby="person-master">
        <h2 id="person-master" className="person-section-title">{t("person.sections.master")}</h2>
        <div className="three-col">
          <label className="field-stack">
            <span className="field-label">{t("editModal.firstName")}</span>
            <input value={draft.first_name} onChange={(event) => set("first_name", event.target.value)} />
          </label>
          <label className="field-stack">
            <span className="field-label">{t("editModal.lastName")}</span>
            <input value={draft.last_name} onChange={(event) => set("last_name", event.target.value)} />
          </label>
          <label className="field-stack">
            <span className="field-label">{t("editModal.displayName")}</span>
            <input value={draft.display_name} onChange={(event) => set("display_name", event.target.value)} required />
          </label>
        </div>
        <label className="field-stack">
          <span className="field-label">{t("editModal.email")}</span>
          <input type="email" value={draft.email} onChange={(event) => set("email", event.target.value)} />
          <span className="field-help">{person.login_enabled ? t("person.emailLoginHelp") : t("person.emailHelp")}</span>
        </label>
        {loginStatus !== "active" ? (
          <label className="checkbox-line">
            <input type="checkbox" checked={draft.notify_without_login} disabled={!draft.email.trim()}
              onChange={(event) => set("notify_without_login", event.target.checked)} />
            <span>{t("editModal.notifyWithoutLogin")}<span className="field-help"> {draft.email.trim() ? t("editModal.notifyWithoutLoginHint") : t("editModal.notifyWithoutLoginNeedsEmail")}</span></span>
          </label>
        ) : null}
      </section>

      <section className="section-card person-section" aria-labelledby="person-membership">
        <h2 id="person-membership" className="person-section-title">{t("person.sections.membership")}</h2>
        <div className="two-col">
          <label className="field-stack">
            <span className="field-label">{t("editModal.joinedAt")}</span>
            <DateInput value={draft.joined_at} onChange={(value) => set("joined_at", value)} />
          </label>
          <label className="field-stack">
            <span className="field-label">{t("editModal.leftAt")}</span>
            <DateInput value={draft.left_at} onChange={(value) => set("left_at", value)} />
          </label>
        </div>
        <span className="field-help">{t("person.membershipHelp")}</span>
        <label className="checkbox-line">
          <input type="checkbox" checked={draft.is_active} onChange={(event) => set("is_active", event.target.checked)} />
          {t("editModal.active")}
        </label>
        <div className="field-stack">
          <span className="field-label">{t("editModal.templates")}</span>
          <div className="participant-check-grid">
            {templates.map((template) => {
              const checked = draft.template_ids.includes(template.id);
              return (
                <label key={template.id} className={`participant-check-card${checked ? " participant-check-card-active" : ""}`}>
                  <input
                    type="checkbox"
                    checked={checked}
                    onChange={(event) => set("template_ids", (event.target.checked
                      ? [...new Set([...draft.template_ids, template.id])]
                      : draft.template_ids.filter((id) => id !== template.id)).sort())}
                  />
                  <div>
                    <strong>{template.name}</strong>
                    <div className="muted">{template.description ?? t("editModal.noDescription")}</div>
                  </div>
                </label>
              );
            })}
          </div>
        </div>
      </section>

      {permissions.financeRead ? (
        <section className="section-card person-section" aria-labelledby="person-tariff">
          <div className="person-section-head">
            <h2 id="person-tariff" className="person-section-title">{t("person.sections.tariff")}</h2>
            {permissions.financeManage ? <Link href="/fine-settings" className="person-section-link">{t("person.manageTariffs")}</Link> : null}
          </div>
          {permissions.financeManage ? (
            <label className="field-stack">
              <span className="field-label">{t("person.tariff")}</span>
              <Select value={draft.tariff_id} onChange={(event) => set("tariff_id", event.target.value)}>
                <option value="">{tariffLabel("")}</option>
                {tariffs.filter((tariff) => !tariff.is_default).map((tariff) => (
                  <option key={tariff.id} value={tariff.id}>{tariff.name}</option>
                ))}
              </Select>
            </label>
          ) : (
            <p className="muted">{t("person.tariffReadOnly", { tariff: tariffLabel(saved.tariff_id) })}</p>
          )}
        </section>
      ) : null}

      <section className="section-card person-section" aria-labelledby="person-login">
        <div className="person-section-head">
          <h2 id="person-login" className="person-section-title">{t("person.sections.login")}</h2>
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
        {permissions.access ? <Link href="/users/roles" className="person-section-link">{t("person.rolesExplained")}</Link> : null}

        {permissions.access ? (
          <div className="person-login-row">
            <span className="field-help">
              {!previewAllowed ? t("person.previewNotAllowed") : draft.role_ids.join() !== saved.role_ids.join() ? t("person.previewSavedOnly") : t("person.previewHelp")}
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
      </section>

      {!isSelf ? (
        <section className="section-card person-section" aria-labelledby="person-more">
          <h2 id="person-more" className="person-section-title">{t("person.sections.more")}</h2>
          {permissions.dataExport ? (
            <div className="person-login-row">
              <span className="field-help">{t("person.exportHelp")}</span>
              <button type="button" className="button-secondary" onClick={() => setExportOpen(true)}>{t("personalData.action")}</button>
            </div>
          ) : null}
          <div className="person-login-row">
            <span className="field-help">{t("person.deleteHelp")}</span>
            <button type="button" className="button-secondary button-danger" onClick={() => void deletePerson()}>{t("person.delete")}</button>
          </div>
        </section>
      ) : null}

      {dirty ? (
        <div className="person-unsaved-bar" role="region" aria-label={t("person.unsaved")}>
          <span className="person-unsaved-text">{blocker ? t(`person.blockers.${blocker}`) : t("person.unsaved")}</span>
          <button type="button" className="button-ghost" disabled={saving} onClick={() => setDraft(saved)}>{t("person.discard")}</button>
          <button type="button" className="button-primary" disabled={saving || blocker !== null} onClick={() => void save()}>{t("editModal.save")}</button>
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
