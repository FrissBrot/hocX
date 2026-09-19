"use client";

import { FormEvent, useState } from "react";

import { Badge } from "@/components/ui/badge";
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
      showToast("Link erstellt", "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : "Link konnte nicht erstellt werden", "error");
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
      showToast(error instanceof Error ? error.message : "Link konnte nicht umbenannt werden", "error");
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
      showToast(error instanceof Error ? error.message : "Standard-Link konnte nicht gesetzt werden", "error");
    }
  }

  async function regenerate(link: SubmissionLink) {
    const ok = await confirm({
      message: `Neuen Link für „${link.name}“ erzeugen? Die bisherige Adresse funktioniert danach sofort nicht mehr.`,
      tone: "danger",
    });
    if (!ok) return;
    try {
      replace(await browserApiFetch<SubmissionLink>(`/api/submission-links/${link.id}/regenerate`, { method: "POST" }));
      showToast("Neuer Link erzeugt", "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : "Link konnte nicht erneuert werden", "error");
    }
  }

  async function remove(link: SubmissionLink) {
    const usage =
      link.assignment_count > 0
        ? ` ${link.assignment_count} Abgabe${link.assignment_count === 1 ? " ist" : "n sind"} darüber erreichbar und danach nicht mehr über diesen Link.`
        : "";
    const ok = await confirm({
      message: `Link „${link.name}“ löschen? Die Adresse funktioniert danach nicht mehr.${usage}`,
      tone: "danger",
    });
    if (!ok) return;
    try {
      await browserApiFetch(`/api/submission-links/${link.id}`, { method: "DELETE" });
      onLinksChange(links.filter((item) => item.id !== link.id));
      onLinkRemoved(link.id);
      showToast("Link gelöscht", "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : "Link konnte nicht gelöscht werden", "error");
    }
  }

  return (
    <div className="grid">
      <p className="muted">
        Die öffentliche Abgabebox ist nur über einen Link erreichbar. Die Adresse enthält einen zufälligen Schlüssel – wer den
        Link kennt, kann die damit verknüpften Abgaben nutzen. Welche Abgabe über welche Links erreichbar ist, wird bei der Abgabe
        selbst festgelegt.
      </p>

      {links.length === 0 ? <p className="muted">Noch keine Links – ohne Link ist keine Abgabe erreichbar.</p> : null}

      {links.map((link) => (
        <div key={link.id} className="field-stack" style={{ borderTop: "1px solid var(--border)", paddingTop: 12 }}>
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
                  Speichern
                </button>
                <button type="button" className="button-ghost" onClick={() => setEditingId(null)}>
                  Abbrechen
                </button>
              </>
            ) : (
              <>
                <strong>{link.name}</strong>
                {link.is_default ? <Badge variant="success">Standard</Badge> : null}
                <span className="muted" style={{ flex: 1 }}>
                  {link.assignment_count} Abgabe{link.assignment_count === 1 ? "" : "n"}
                </span>
                <button
                  type="button"
                  className="subm-sidebar-icon-button"
                  onClick={() => {
                    setEditingId(link.id);
                    setEditName(link.name);
                  }}
                  aria-label="Umbenennen"
                  title="Umbenennen"
                >
                  ✎
                </button>
                <button
                  type="button"
                  className="subm-sidebar-icon-button subm-sidebar-icon-button-danger"
                  onClick={() => void remove(link)}
                  aria-label="Löschen"
                  title="Löschen"
                >
                  ×
                </button>
              </>
            )}
          </div>
          <CopyField label="Link" value={link.url} />
          <div style={{ display: "flex", gap: "var(--space-2)", flexWrap: "wrap" }}>
            {!link.is_default ? (
              <button type="button" className="button-ghost" onClick={() => void makeDefault(link)}>
                Als Standard festlegen
              </button>
            ) : null}
            <button type="button" className="button-ghost" onClick={() => void regenerate(link)}>
              Neuen Schlüssel erzeugen
            </button>
          </div>
        </div>
      ))}

      <form className="field-stack" onSubmit={createLink} style={{ borderTop: "1px solid var(--border)", paddingTop: 12 }}>
        <span className="field-label">Neuer Link</span>
        <div style={{ display: "flex", gap: "var(--space-2)" }}>
          <input
            value={newName}
            maxLength={80}
            onChange={(e) => setNewName(e.target.value)}
            placeholder="Name, z. B. „Eltern“ oder „Leiterteam“"
            required
            style={{ flex: 1 }}
          />
          <button type="submit" className="button-secondary" disabled={!newName.trim()}>
            Link erstellen
          </button>
        </div>
        <span className="field-help">Der Name ist nur für dich sichtbar – die Adresse selbst ist zufällig generiert.</span>
      </form>
    </div>
  );
}
