"use client";

import { useMemo } from "react";
import { useTranslations } from "next-intl";

import { Badge } from "@/components/ui/badge";
import { roleName } from "@/lib/permissions";
import { PERMISSION_AREAS, PERMISSIONS, type PermissionKey } from "@/lib/permissions.generated";
import type { RoleRead } from "@/types/api";

const REQUIRES_MFA = new Set(PERMISSIONS.filter((permission) => permission.requiresMfa).map((permission) => permission.key));

/** Rollen eines Kontos ankreuzen (mehrere möglich). Rollen mit Berechtigungen, die der Akteur
 * selbst nicht hat, sind gesperrt - das Backend lehnt sie ohnehin ab (keine Rechteausweitung). */
export function RoleChecklist({
  roles,
  value,
  onChange,
  actorPermissions,
}: {
  roles: RoleRead[];
  value: string[];
  onChange: (roleIds: string[]) => void;
  actorPermissions: readonly string[];
}) {
  const t = useTranslations("roles");
  const tNav = useTranslations("nav");
  const tUsers = useTranslations("users");
  const own = useMemo(() => new Set(actorPermissions), [actorPermissions]);
  const selected = new Set(value);
  const needsMfa = roles.some((role) => selected.has(role.id) && role.permissions.some((key) => REQUIRES_MFA.has(key as PermissionKey)));

  return (
    <div className="field-stack" role="group" aria-label={t("userRoles.label")}>
      <span className="field-label">{t("userRoles.label")}</span>
      <div className="roles-checklist">
        {roles.map((role) => {
          const allowed = role.permissions.every((key) => own.has(key));
          const checked = selected.has(role.id);
          const description = role.description ?? (role.system_key ? tUsers(`roleDescriptions.${role.system_key}`) : null);
          return (
            <label key={role.id} className="roles-checklist-option">
              <input
                type="checkbox"
                checked={checked}
                disabled={!allowed}
                onChange={(event) =>
                  onChange(event.target.checked ? [...value, role.id] : value.filter((roleId) => roleId !== role.id))
                }
              />
              <span className="roles-checklist-text">
                <span className="roles-checklist-name">{roleName(role, tNav)}</span>
                {description ? <span className="field-help">{description}</span> : null}
                {!allowed ? <span className="field-help">{t("notOwned")}</span> : null}
              </span>
            </label>
          );
        })}
      </div>
      <span className="field-help">{t("userRoles.help")}</span>
      {needsMfa ? <span className="field-help">{t("userRoles.mfaWarning")}</span> : null}
    </div>
  );
}

/** Effektive Berechtigungen der gewählten Rollen (Vereinigungsmenge), nach Bereich gruppiert, je
 * Berechtigung mit den Rollen, aus denen sie stammt. Reine Ableitung, keine eigene API. */
export function EffectivePermissions({
  roles,
  roleIds,
  enabledFeatures,
}: {
  roles: RoleRead[];
  roleIds: string[];
  enabledFeatures: readonly string[];
}) {
  const t = useTranslations("roles");
  const tNav = useTranslations("nav");
  const sources = useMemo(() => {
    const result = new Map<string, string[]>();
    for (const role of roles) {
      if (!roleIds.includes(role.id)) continue;
      for (const key of role.permissions) {
        result.set(key, [...(result.get(key) ?? []), roleName(role, tNav)]);
      }
    }
    return result;
  }, [roles, roleIds, tNav]);

  const areas = PERMISSION_AREAS.map((area) => ({
    area,
    permissions: PERMISSIONS.filter((permission) => permission.area === area && sources.has(permission.key)),
  })).filter((group) => group.permissions.length > 0);

  return (
    <div className="field-stack">
      <span className="field-label">{t("effective.title")}</span>
      {areas.length === 0 ? (
        <span className="muted">{t("effective.none")}</span>
      ) : (
        <div className="roles-effective">
          {areas.map(({ area, permissions }) => (
            <div key={area} className="roles-effective-area">
              <span className="roles-area-title">{t(`areas.${area}`)}</span>
              <ul className="roles-effective-list">
                {permissions.map((permission) => (
                  <li key={permission.key}>
                    <span>{t(`permissions.${permission.key}.label`)}</span>
                    <span className="field-help">{t("effective.via", { roles: (sources.get(permission.key) ?? []).join(", ") })}</span>
                    {permission.feature && !enabledFeatures.includes(permission.feature) ? (
                      <Badge variant="neutral">{t("featureMissing")}</Badge>
                    ) : null}
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
