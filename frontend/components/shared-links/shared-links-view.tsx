"use client";

import { useEffect, useMemo, useState } from "react";

import { ActionMenu } from "@/components/ui/action-menu";
import { Badge, BadgeVariant } from "@/components/ui/badge";
import { DataTable, DataToolbar } from "@/components/ui/data-table";
import { EmptyState } from "@/components/ui/empty-state";
import { FilterTabs } from "@/components/ui/filter-tabs";
import { useConfirm } from "@/contexts/confirm-context";
import { useToast } from "@/contexts/toast-context";
import { browserApiFetch } from "@/lib/api/client";
import { formatDateTime } from "@/lib/utils/format";
import { ShareLink } from "@/types/api";

const STATUS_LABEL: Record<ShareLink["status"], string> = { active: "Aktiv", expired: "Abgelaufen", revoked: "Widerrufen" };
const STATUS_VARIANT: Record<ShareLink["status"], BadgeVariant> = { active: "success", expired: "neutral", revoked: "danger" };

type Filter = "active" | "all";

export function SharedLinksView({ initialLinks }: { initialLinks: ShareLink[] }) {
  const toast = useToast();
  const confirm = useConfirm();
  const [links, setLinks] = useState<ShareLink[]>(initialLinks);
  const [filter, setFilter] = useState<Filter>("active");

  useEffect(() => {
    browserApiFetch<ShareLink[]>("/api/share-links").then((data) => setLinks(data ?? [])).catch(() => {});
  }, []);

  const visible = useMemo(() => (filter === "active" ? links.filter((link) => link.status === "active") : links), [links, filter]);

  async function copyUrl(link: ShareLink) {
    try {
      await navigator.clipboard.writeText(`${window.location.origin}${link.url}`);
      toast("Link kopiert.", "success");
    } catch {
      toast("Link konnte nicht kopiert werden.", "error");
    }
  }

  async function revoke(link: ShareLink) {
    const ok = await confirm({ tone: "danger", message: `Link „${link.name}“ widerrufen? Er funktioniert danach nicht mehr.`, confirmLabel: "Widerrufen" });
    if (!ok) return;
    try {
      await browserApiFetch(`/api/share-links/${link.id}`, { method: "DELETE" });
      setLinks((current) => current.map((item) => (item.id === link.id ? { ...item, status: "revoked", revoked_at: new Date().toISOString() } : item)));
      toast("Link widerrufen.", "success");
    } catch {
      toast("Link konnte nicht widerrufen werden.", "error");
    }
  }

  return (
    <div className="grid">
      <div className="page-header">
        <div>
          <h1 className="page-title">Geteilte Links</h1>
          <p className="muted">Öffentliche Download-Links für Dateien und Fotos dieses Mandanten.</p>
        </div>
      </div>

      {links.length === 0 ? (
        <EmptyState
          title="Noch keine Links vorhanden"
          description="Über „Teilen“ bei Dateien, Fotos oder einem Fotoalbum lässt sich ein Download-Link ohne Anmeldung erzeugen."
        />
      ) : (
        <>
          <div className="list-filter-row list-filter-row-compact">
            <FilterTabs
              options={[
                { value: "active", label: "Aktiv", count: links.filter((link) => link.status === "active").length },
                { value: "all", label: "Alle", count: links.length },
              ]}
              value={filter}
              onChange={(value) => setFilter(value as Filter)}
            />
          </div>
          <DataTable columns={["Name", "Umfang", "Erstellt von", "Ablauf", "Status", ""]} emptyMessage="Keine Links in dieser Ansicht.">
            {visible.map((link) => (
              <tr key={link.id}>
                <td>{link.name}</td>
                <td>{link.album_name ? `Album „${link.album_name}“` : `${link.file_count} ${link.file_count === 1 ? "Datei" : "Dateien"}`}</td>
                <td>{link.created_by_name ?? <span className="muted">–</span>}</td>
                <td>{link.expires_at ? formatDateTime(link.expires_at) : <span className="muted">Kein Ablauf</span>}</td>
                <td><Badge variant={STATUS_VARIANT[link.status]}>{STATUS_LABEL[link.status]}</Badge></td>
                <td>
                  <ActionMenu
                    ariaLabel={`Aktionen für ${link.name}`}
                    items={[
                      { label: "Link kopieren", onClick: () => void copyUrl(link) },
                      ...(link.status === "active" ? [{ label: "Widerrufen", danger: true, onClick: () => void revoke(link) }] : []),
                    ]}
                  />
                </td>
              </tr>
            ))}
          </DataTable>
        </>
      )}
    </div>
  );
}
