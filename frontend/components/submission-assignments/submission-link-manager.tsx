"use client";

import { FormEvent, useState } from "react";
import { useTranslations } from "next-intl";

import { Badge } from "@/components/ui/badge";
import { ActionIcon } from "@/components/ui/action-icons";
import { CopyField } from "@/components/ui/copy-field";
import { browserApiFetch } from "@/lib/api/client";
import { useConfirm } from "@/contexts/confirm-context";
import { useToast } from "@/contexts/toast-context";
import { SubmissionLink } from "@/types/api";

type Props = {
  links: SubmissionLink[];
  onLinksChange: (links: SubmissionLink[]) => void;
  // Called after a link was deleted/regenerated so the parent can refresh what depends on it
  // (the Abgaben's link_ids).
  onLinkRemoved: (linkId: string) => void;
};

export function SubmissionLinkManager({ links, onLinksChange, onLinkRemoved }: Props) {
  const t = useTranslations("submissionAssignments");
  const tCommon = useTranslations("common");
  const showToast = useToast();
  const confirm = useConfirm();
  const [newName, setNewName] = useState("");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editName, setEditName] = useState("");

  function replace(updated: SubmissionLink) {
    onLinksChange(
      links.map((link) => {
        if (link.id === updated.id) return updated;
        // Only one default link per tenant - the server cleared the flag on the previous one.
        return updated.is_default ? { ...link, is_default: false } : link;
      })
    );
  }

  async function createLink(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    try {
      const created = await browserApiFetch<SubmissionLink>("/api/submission-links", {
        method: "POST",
        body: JSON.stringify({ name: newName, is_default: false }),
      });
      onLinksChange([...links, created]);
      setNewName("");
      showToast(t("linkCreatedToast"), "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("linkCreateFailed"), "error");
    }
  }

  async function saveName(link: SubmissionLink) {
    if (editName.trim() === link.name) {
      setEditingId(null);
      return;
    }
    try {
      replace(
        await browserApiFetch<SubmissionLink>(`/api/submission-links/${link.id}`, {
          method: "PATCH",
          body: JSON.stringify({ name: editName }),
        })
      );
      setEditingId(null);
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("linkRenameFailed"), "error");
    }
  }

  async function makeDefault(link: SubmissionLink) {
    try {
      replace(
        await browserApiFetch<SubmissionLink>(`/api/submission-links/${link.id}`, {
          method: "PATCH",
          body: JSON.stringify({ is_default: true }),
        })
      );
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("defaultLinkSetFailed"), "error");
    }
  }

  async function regenerate(link: SubmissionLink) {
    const ok = await confirm({
      message: t("regenerateConfirm", { name: link.name }),
      tone: "danger",
    });
    if (!ok) return;
    try {
      replace(await browserApiFetch<SubmissionLink>(`/api/submission-links/${link.id}/regenerate`, { method: "POST" }));
      showToast(t("linkRegeneratedToast"), "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("linkRegenerateFailed"), "error");
    }
  }

  async function remove(link: SubmissionLink) {
    const usage = link.assignment_count > 0 ? t("removeUsageSuffix", { count: link.assignment_count }) : "";
    const ok = await confirm({
      message: t("deleteLinkConfirm", { name: link.name, usage }),
      tone: "danger",
    });
    if (!ok) return;
    try {
      await browserApiFetch(`/api/submission-links/${link.id}`, { method: "DELETE" });
      onLinksChange(links.filter((item) => item.id !== link.id));
      onLinkRemoved(link.id);
      showToast(t("linkDeletedToast"), "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("linkDeleteFailed"), "error");
    }
  }

  return (
    <div className="grid">
      <p className="muted">
        {t("linkManagerIntro")}
      </p>

      {links.length === 0 ? <p className="muted">{t("noLinksYet")}</p> : null}

      {links.map((link) => (
        <div key={link.id} className="field-stack" style={{ borderTop: "1px solid var(--border)", paddingTop: "var(--space-3)" }}>
          <div style={{ display: "flex", alignItems: "center", gap: "var(--space-2)", flexWrap: "wrap" }}>
            {editingId === link.id ? (
              <>
                <input
                  autoFocus
                  value={editName}
                  maxLength={80}
                  onChange={(e) => setEditName(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      e.preventDefault();
                      void saveName(link);
                    }
                    if (e.key === "Escape") {
                      e.stopPropagation();
                      setEditingId(null);
                    }
                  }}
                  style={{ flex: 1, minWidth: 160 }}
                />
                <button type="button" className="button-secondary" onClick={() => void saveName(link)} disabled={!editName.trim()}>
                  {tCommon("save")}
                </button>
                <button type="button" className="button-ghost" onClick={() => setEditingId(null)}>
                  {t("cancel")}
                </button>
              </>
            ) : (
              <>
                <strong>{link.name}</strong>
                {link.is_default ? <Badge variant="success">{t("defaultLabel")}</Badge> : null}
                <span className="muted" style={{ flex: 1 }}>
                  {t("assignmentCountSuffix", { count: link.assignment_count })}
                </span>
                <button
                  type="button"
                  className="subm-sidebar-icon-button"
                  onClick={() => {
                    setEditingId(link.id);
                    setEditName(link.name);
                  }}
                  aria-label={t("renameLabel")}
                  title={t("renameLabel")}
                >
                  <ActionIcon name="edit" />
                </button>
                <button
                  type="button"
                  className="subm-sidebar-icon-button subm-sidebar-icon-button-danger"
                  onClick={() => void remove(link)}
                  aria-label={t("delete")}
                  title={t("delete")}
                >
                  <ActionIcon name="delete" />
                </button>
              </>
            )}
          </div>
          <CopyField label={t("linkFieldLabel")} value={link.url} />
          <div style={{ display: "flex", gap: "var(--space-2)", flexWrap: "wrap" }}>
            {!link.is_default ? (
              <button type="button" className="button-ghost" onClick={() => void makeDefault(link)}>
                {t("makeDefaultButton")}
              </button>
            ) : null}
            <button type="button" className="button-ghost" onClick={() => void regenerate(link)}>
              {t("regenerateButton")}
            </button>
          </div>
        </div>
      ))}

      <form className="field-stack" onSubmit={createLink} style={{ borderTop: "1px solid var(--border)", paddingTop: "var(--space-3)" }}>
        <span className="field-label">{t("newLinkLabel")}</span>
        <div style={{ display: "flex", gap: "var(--space-2)" }}>
          <input
            value={newName}
            maxLength={80}
            onChange={(e) => setNewName(e.target.value)}
            placeholder={t("newLinkNamePlaceholder")}
            required
            style={{ flex: 1 }}
          />
          <button type="submit" className="button-secondary" disabled={!newName.trim()}>
            {t("createLinkButton")}
          </button>
        </div>
        <span className="field-help">{t("newLinkHelp")}</span>
      </form>
    </div>
  );
}
