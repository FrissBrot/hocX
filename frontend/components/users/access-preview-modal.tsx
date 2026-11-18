"use client";

import { useEffect, useMemo, useState } from "react";
import { useTranslations } from "next-intl";

import { buildNav, type NavSession } from "@/components/ui/app-shell-nav";
import { Badge } from "@/components/ui/badge";
import { Modal } from "@/components/ui/modal";
import { StatusBanner } from "@/components/ui/status-banner";
import { browserApiFetch } from "@/lib/api/client";
import { apiErrorMessage } from "@/lib/api/error-message";
import { roleName } from "@/lib/permissions";
import { PERMISSION_AREAS, PERMISSIONS } from "@/lib/permissions.generated";
import type { AccessPreview } from "@/types/api";

type Props = {
  open: boolean;
  onClose: () => void;
  // public_id des Kontos (= Personen-ID)
  userId: string;
  name: string;
};

/** «Ansehen als …» (Plan «Berechtigungen», Phase 7): zeigt, welche Menüpunkte, Rechte und Abgaben
 * ein Konto sieht. Nur lesend - das Backend berechnet die Rechte ohne Sitzung des Kontos
 * (GET /api/users/{id}/access-preview, access.manage, im Verlauf vermerkt); die Navigation kommt
 * aus derselben Funktion wie die echte Seitenleiste (buildNav). */
export function AccessPreviewModal({ open, onClose, userId, name }: Props) {
  const t = useTranslations("roles");
  const tNav = useTranslations("nav");
  const tSecurity = useTranslations("security");
  const [preview, setPreview] = useState<AccessPreview | null>(null);
  // Fehler roh speichern und erst beim Rendern übersetzen (Effekt hängt nur an Konto und open)
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setPreview(null);
    setError(null);
    browserApiFetch<AccessPreview>(`/api/users/${userId}/access-preview`)
      .then((result) => {
        if (!cancelled) setPreview(result);
      })
      .catch((caught: unknown) => {
        if (!cancelled) setError(caught ?? new Error());
      });
    return () => {
      cancelled = true;
    };
  }, [open, userId]);

  const nav = useMemo(() => {
    if (!preview) return [];
    const session: NavSession = {
      permissions: preview.permissions.map((item) => item.key),
      current_tenant: {
        id: "",
        name: "",
        profile_image_path: null,
        profile_image_url: null,
        enabled_features: preview.enabled_features,
        read_only_features: preview.read_only_features,
      },
    };
    return buildNav(session);
  }, [preview]);

  const areas = useMemo(() => {
    if (!preview) return [];
    const byKey = new Map(preview.permissions.map((item) => [item.key, item]));
    return PERMISSION_AREAS.map((area) => ({
      area,
      items: PERMISSIONS.filter((permission) => permission.area === area && byKey.has(permission.key)).map((permission) => byKey.get(permission.key)!),
    })).filter((group) => group.items.length > 0);
  }, [preview]);

  return (
    <Modal open={open} onClose={onClose} title={t("preview.title", { name })} description={t("preview.description")} size="wide">
      {error ? <StatusBanner tone="error" message={apiErrorMessage(error, tSecurity, "apiErrors", t("preview.loadFailed"))} /> : null}
      {!preview && !error ? <p className="muted">{t("preview.loading")}</p> : null}
      {preview ? (
        <div className="access-preview">
          <StatusBanner tone="neutral" message={t("preview.readOnlyHint")} />
          {!preview.login_enabled || !preview.is_active ? <StatusBanner tone="warning" message={t("preview.noLogin")} /> : null}

          <div className="two-col">
            <div className="field-stack">
              <span className="field-label">{t("userRoles.label")}</span>
              <span className="access-role-chips">
                {preview.roles.length
                  ? preview.roles.map((role) => <Badge key={role.id} variant="neutral">{roleName(role, tNav)}</Badge>)
                  : <span className="muted">{t("preview.noRoles")}</span>}
              </span>
            </div>
            <div className="field-stack">
              <span className="field-label">{t("preview.mfa")}</span>
              <span className="access-role-chips">
                <Badge variant={preview.mfa_required ? "warning" : "neutral"}>{preview.mfa_required ? t("preview.mfaRequired") : t("preview.mfaOptional")}</Badge>
                <Badge variant={preview.mfa_active ? "success" : "neutral"} dot>{preview.mfa_active ? t("preview.mfaActive") : t("preview.mfaInactive")}</Badge>
              </span>
            </div>
          </div>

          <div className="field-stack">
            <span className="field-label">{t("preview.navigation")}</span>
            {nav.length === 0 ? (
              <span className="muted">{t("preview.navigationEmpty")}</span>
            ) : (
              <div className="access-preview-nav">
                {nav.map((group) => (
                  <div key={group.titleKey ?? "start"} className="access-preview-nav-group">
                    <span className="roles-area-title">{group.titleKey ? tNav(group.titleKey) : t("preview.startGroup")}</span>
                    <ul className="access-preview-list">
                      {group.links.map((link) => <li key={link.href}>{tNav(link.labelKey)}</li>)}
                    </ul>
                  </div>
                ))}
              </div>
            )}
          </div>

          <div className="field-stack">
            <span className="field-label">{t("effective.title")}</span>
            {areas.length === 0 ? (
              <span className="muted">{t("effective.none")}</span>
            ) : (
              <div className="roles-effective">
                {areas.map(({ area, items }) => (
                  <div key={area} className="roles-effective-area">
                    <span className="roles-area-title">{t(`areas.${area}`)}</span>
                    <ul className="access-preview-list">
                      {items.map((item) => (
                        <li key={item.key}>
                          <span>{t(`permissions.${item.key}.label`)}</span>
                          {item.scope === "assigned" ? <Badge variant="info">{t("scopes.assigned")}</Badge> : null}
                          {item.feature_access === "none" ? <Badge variant="neutral">{t("featureMissing")}</Badge> : null}
                          {item.feature_access === "read_only" ? <Badge variant="neutral">{t("preview.featureReadOnly")}</Badge> : null}
                        </li>
                      ))}
                    </ul>
                  </div>
                ))}
              </div>
            )}
          </div>

          {preview.submissions ? (
            <div className="field-stack">
              <span className="field-label">{t("preview.submissions")}</span>
              {preview.submissions.scope === "all" ? (
                <span>{t("preview.submissionsAll", { count: preview.submissions.visible_count })}</span>
              ) : (
                <>
                  <span>{t("preview.submissionsAssigned", { count: preview.submissions.visible_count })}</span>
                  {preview.submissions.assigned.length > 0 ? (
                    <ul className="access-preview-list">
                      {preview.submissions.assigned.map((item) => <li key={item.id}>{item.title}</li>)}
                    </ul>
                  ) : null}
                </>
              )}
            </div>
          ) : null}
        </div>
      ) : null}
    </Modal>
  );
}
