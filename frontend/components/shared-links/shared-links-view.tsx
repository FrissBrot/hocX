"use client";

import { useEffect, useMemo, useState } from "react";
import { useTranslations } from "next-intl";

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

const STATUS_VARIANT: Record<ShareLink["status"], BadgeVariant> = { active: "success", expired: "neutral", revoked: "danger" };

type Filter = "active" | "all";

export function SharedLinksView({ initialLinks }: { initialLinks: ShareLink[] }) {
  const t = useTranslations("sharedLinks");
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
      toast(t("toasts.copied"), "success");
    } catch {
      toast(t("toasts.copyFailed"), "error");
    }
  }

  async function revoke(link: ShareLink) {
    const ok = await confirm({ tone: "danger", message: t("revokeConfirm", { name: link.name }), confirmLabel: t("revokeConfirmLabel") });
    if (!ok) return;
    try {
      await browserApiFetch(`/api/share-links/${link.id}`, { method: "DELETE" });
      setLinks((current) => current.map((item) => (item.id === link.id ? { ...item, status: "revoked", revoked_at: new Date().toISOString() } : item)));
      toast(t("toasts.revoked"), "success");
    } catch {
      toast(t("toasts.revokeFailed"), "error");
    }
  }

  return (
    <div className="grid">
      <div className="page-header">
        <div>
          <h1 className="page-title">{t("page.title")}</h1>
          <p className="muted">{t("page.description")}</p>
        </div>
      </div>

      {links.length === 0 ? (
        <EmptyState
          title={t("emptyTitle")}
          description={t("emptyDescription")}
        />
      ) : (
        <>
          <div className="list-filter-row list-filter-row-compact">
            <FilterTabs
              options={[
                { value: "active", label: t("filterActive"), count: links.filter((link) => link.status === "active").length },
                { value: "all", label: t("filterAll"), count: links.length },
              ]}
              value={filter}
              onChange={(value) => setFilter(value as Filter)}
            />
          </div>
          <DataTable columns={[t("table.columnName"), t("table.columnScope"), t("table.columnCreatedBy"), t("table.columnExpiry"), t("table.columnStatus"), ""]} emptyMessage={t("table.empty")}>
            {visible.map((link) => (
              <tr key={link.id}>
                <td>{link.name}</td>
                <td>{link.album_name ? t("table.albumScope", { name: link.album_name }) : t("table.fileScope", { count: link.file_count })}</td>
                <td>{link.created_by_name ?? <span className="muted">–</span>}</td>
                <td>{link.expires_at ? formatDateTime(link.expires_at) : <span className="muted">{t("table.noExpiry")}</span>}</td>
                <td><Badge variant={STATUS_VARIANT[link.status]}>{t(`status.${link.status}`)}</Badge></td>
                <td>
                  <ActionMenu
                    ariaLabel={t("table.actionsLabel", { name: link.name })}
                    items={[
                      { label: t("table.copyLink"), onClick: () => void copyUrl(link) },
                      ...(link.status === "active" ? [{ label: t("table.revoke"), danger: true, onClick: () => void revoke(link) }] : []),
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
