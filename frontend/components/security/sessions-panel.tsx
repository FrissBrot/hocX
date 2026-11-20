"use client";

import { useCallback, useEffect, useState } from "react";
import { useLocale, useTranslations } from "next-intl";

import { Badge } from "@/components/ui/badge";
import { DataTable } from "@/components/ui/data-table";
import { useConfirm } from "@/contexts/confirm-context";
import { useToast } from "@/contexts/toast-context";
import { browserApiFetch } from "@/lib/api/client";
import { apiErrorMessage } from "@/lib/api/error-message";
import { formatDateTime } from "@/lib/utils/format";
import type { SessionDeviceList } from "@/types/api";

/**
 * «Angemeldete Geräte» im Profil › Sicherheit (Auth-Audit 2026-11-20, SEC-AUTH-011): aktive
 * Sitzungen mit grobem Gerät und letzter Aktivität, einzelne Sitzung abmelden, alle anderen
 * abmelden. Keine IP-Adressen - das Backend speichert sie nicht.
 */
export function SessionsPanel({ open }: { open: boolean }) {
  const t = useTranslations("security.sessions");
  const tSecurity = useTranslations("security");
  const locale = useLocale();
  const confirm = useConfirm();
  const showToast = useToast();
  const [data, setData] = useState<SessionDeviceList | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      setData(await browserApiFetch<SessionDeviceList>("/api/users/me/sessions"));
    } catch (error) {
      showToast(apiErrorMessage(error, tSecurity, "apiErrors", t("loadFailed")), "error");
    }
  }, [showToast, t, tSecurity]);

  useEffect(() => {
    if (open) void load();
    // Nur beim Öffnen laden (load hängt an nicht referenzstabilen Übersetzungsfunktionen)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  async function revoke(id: string) {
    if (!(await confirm({ message: t("revokeConfirm"), tone: "danger", confirmLabel: t("revoke") }))) return;
    setBusy(true);
    try {
      await browserApiFetch(`/api/users/me/sessions/${encodeURIComponent(id)}`, { method: "DELETE" });
      showToast(t("revoked"), "success");
      await load();
    } catch (error) {
      showToast(apiErrorMessage(error, tSecurity, "apiErrors", t("revokeFailed")), "error");
    } finally {
      setBusy(false);
    }
  }

  async function revokeOthers() {
    if (!(await confirm({ message: t("revokeOthersConfirm"), tone: "danger", confirmLabel: t("revokeOthers") }))) return;
    setBusy(true);
    try {
      const result = await browserApiFetch<{ revoked: number }>("/api/users/me/sessions/revoke-others", { method: "POST" });
      showToast(t("revokedOthers", { count: result.revoked }), "success");
      await load();
    } catch (error) {
      showToast(apiErrorMessage(error, tSecurity, "apiErrors", t("revokeFailed")), "error");
    } finally {
      setBusy(false);
    }
  }

  const others = data?.sessions.filter((session) => !session.current).length ?? 0;
  return (
    <div className="grid">
      <div>
        <h3>{t("title")}</h3>
        <p className="muted">{t("description")}</p>
      </div>
      <DataTable
        emptyMessage={data ? t("empty") : t("loading")}
        columns={[t("columns.device"), t("columns.lastSeen"), t("columns.since"), t("columns.actions")]}
      >
        {(data?.sessions ?? []).map((session) => (
          <tr key={session.id}>
            <td>
              <strong>{session.user_agent_family ?? t("unknownDevice")}</strong>{" "}
              {session.current ? <Badge variant="success">{t("current")}</Badge> : null}
              {session.via_bridge ? <span className="field-help"> {t("viaBridge", { host: session.host ?? "" })}</span> : null}
            </td>
            <td>{formatDateTime(session.last_seen_at, locale)}</td>
            <td>{formatDateTime(session.created_at, locale)}</td>
            <td>
              {session.current ? null : (
                <button type="button" className="button-danger" onClick={() => void revoke(session.id)} disabled={busy}>
                  {t("revoke")}
                </button>
              )}
            </td>
          </tr>
        ))}
      </DataTable>
      {data?.legacy_session ? <p className="field-help">{t("legacyHint")}</p> : null}
      <div className="table-actions table-actions-start">
        <button type="button" className="button-secondary" onClick={() => void revokeOthers()} disabled={busy || (others === 0 && !data?.legacy_session)}>
          {t("revokeOthers")}
        </button>
      </div>
    </div>
  );
}
