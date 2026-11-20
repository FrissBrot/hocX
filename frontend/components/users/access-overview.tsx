"use client";

import type { Route } from "next";
import Link from "next/link";

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";

import { mfaState, rolesNeedMfa, type MfaState } from "@/components/users/access-helpers";
import { Badge } from "@/components/ui/badge";
import { DataTable } from "@/components/ui/data-table";
import { FilterTabs } from "@/components/ui/filter-tabs";
import { SearchInput } from "@/components/ui/search-input";
import { roleName } from "@/lib/permissions";
import { avatarTone, participantInitials } from "@/lib/utils/avatar";
import type { ParticipantInvite, RoleRead, UserSummary } from "@/types/api";

type Props = {
  users: UserSummary[];
  invites: ParticipantInvite[];
  roles: RoleRead[];
  tenantRequiresMfa: boolean;
};

type Row = { user: UserSummary; status: "active" | "invited" | "inactive"; mfa: MfaState };

const MFA_BADGE: Record<MfaState, "success" | "warning" | "neutral"> = { active: "success", missing: "warning", optional: "neutral" };

/** Zugriff › Wer hat Zugriff: nur Übersicht. Logins und Rollen ändert man auf der Personenseite
 * (/participants/[id], Konzept «Personen an einem Ort»). */
export function AccessOverview({ users, invites, roles, tenantRequiresMfa }: Props) {
  const t = useTranslations("users");
  const tNav = useTranslations("nav");
  const router = useRouter();
  const [filter, setFilter] = useState<"all" | "mfaMissing">("all");
  const [search, setSearch] = useState("");

  const rows = useMemo<Row[]>(() => {
    const invited = new Set(invites.map((invite) => invite.participant_id));
    return users
      .filter((user) => user.login_enabled || invited.has(user.id))
      .map((user) => {
        const required = tenantRequiresMfa || rolesNeedMfa(roles, user.roles.map((role) => role.id));
        const status: Row["status"] = !user.login_enabled ? "invited" : user.is_active ? "active" : "inactive";
        return { user, status, mfa: user.login_enabled ? mfaState(Boolean(user.mfa_enabled), required) : "optional" };
      })
      .sort((a, b) => a.user.display_name.localeCompare(b.user.display_name));
  }, [users, invites, roles, tenantRequiresMfa]);

  const missingCount = rows.filter((row) => row.mfa === "missing").length;
  const query = search.trim().toLowerCase();
  const visible = rows
    .filter((row) => filter === "all" || row.mfa === "missing")
    .filter((row) => !query || `${row.user.display_name} ${row.user.email ?? ""} ${row.user.roles.map((role) => roleName(role, tNav)).join(" ")}`.toLowerCase().includes(query));

  return (
    <div className="grid">
      <div className="page-header">
        <div>
          <h1 className="page-title">{t("access.title")}</h1>
          <p className="muted">{t("access.description")}</p>
        </div>
      </div>
      <div className="list-filter-row">
        <FilterTabs
          value={filter}
          onChange={setFilter}
          options={[
            { value: "all", label: t("access.filterAll"), count: rows.length },
            { value: "mfaMissing", label: t("access.filterMfaMissing"), count: missingCount },
          ]}
        />
        <div className="list-filter-search">
          <SearchInput value={search} onChange={setSearch} placeholder={t("searchUsers")} />
        </div>
      </div>
      <DataTable
        className="data-table-lg"
        emptyMessage={search.trim() ? t("emptySearch") : t("access.empty")}
        columns={[t("access.columns.person"), t("access.columns.status"), t("access.columns.roles"), t("access.columns.mfa")]}
        footer={<span>{t("access.footerHint")}</span>}
      >
        {visible.map(({ user, status, mfa }) => (
          <tr
            key={user.id}
            className={`table-row-clickable${status === "inactive" ? " participant-row-inactive" : ""}`}
            onClick={() => router.push(`/participants/${user.id}` as Route)} // a11y-ok: Maus-Abkürzung, Tastatur über table-row-link (Name)
          >
            <td>
              <div className="participant-name-cell">
                <span className={`participant-avatar participant-avatar-tone-${avatarTone(user.id)}`} aria-hidden="true">
                  {participantInitials(user)}
                </span>
                <div className="participant-name-text">
                  {/* Tastatur: Name als Link zur Person, die Zeile bleibt für die Maus klickbar */}
                  <Link href={`/participants/${user.id}` as Route} className="table-row-link" onClick={(event) => event.stopPropagation()}>
                    {user.display_name}
                  </Link>
                  <span className="participant-name-sub">{user.email ?? t("access.noEmail")}</span>
                </div>
              </div>
            </td>
            <td>
              <Badge variant={status === "active" ? "success" : status === "invited" ? "info" : "neutral"}>{t(`access.status.${status}`)}</Badge>
            </td>
            <td>
              <span className="access-role-chips">
                {user.roles.length
                  ? user.roles.map((role) => <Badge key={role.id} variant="neutral">{roleName(role, tNav)}</Badge>)
                  : <span className="muted">{t("access.noRole")}</span>}
              </span>
            </td>
            <td>{status === "invited" ? <span className="muted">–</span> : <Badge variant={MFA_BADGE[mfa]} dot>{t(`access.mfa.${mfa}`)}</Badge>}</td>
          </tr>
        ))}
      </DataTable>
    </div>
  );
}
