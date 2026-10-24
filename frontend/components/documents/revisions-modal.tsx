"use client";

// Revisionen einer Vorlage: Liste, Vergleich zweier Stände (Strukturvergleich), Wiederherstellen
// eines älteren Stands als neuer Entwurf. Veröffentlichte Stände bleiben unverändert.

import { useEffect, useState } from "react";
import { useLocale, useTranslations } from "next-intl";

import { Badge } from "@/components/ui/badge";
import { Modal } from "@/components/ui/modal";
import { StatusBanner } from "@/components/ui/status-banner";
import { useConfirm } from "@/contexts/confirm-context";
import { useToast } from "@/contexts/toast-context";
import { apiErrorMessage, DocumentTemplateInfo, RevisionDiff, RevisionInfo, studioApi } from "@/lib/documents/api";
import { formatDateTime } from "@/lib/utils/format";

type Props = { template: DocumentTemplateInfo; onClose: () => void; onRestored: () => void };

const STATUS_VARIANT = { draft: "warning", published: "success", superseded: "neutral" } as const;

export function RevisionsModal({ template, onClose, onRestored }: Props) {
  const t = useTranslations("documentStudio");
  const locale = useLocale();
  const toast = useToast();
  const confirm = useConfirm();
  const [revisions, setRevisions] = useState<RevisionInfo[] | null>(null);
  const [compare, setCompare] = useState<string[]>([]);
  const [diff, setDiff] = useState<RevisionDiff | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    studioApi
      .revisions(template.id)
      .then(setRevisions)
      .catch((reason) => setError(apiErrorMessage(reason, t("revisions.loadFailed"))));
    // t/toast sind während der Lebensdauer der Komponente unveränderlich
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [template.id]);

  useEffect(() => {
    setDiff(null);
    if (compare.length !== 2 || !revisions) return;
    const [first, second] = compare.map((id) => revisions.find((item) => item.id === id)!).sort((a, b) => a.revision_no - b.revision_no);
    studioApi
      .compare(template.id, first.id, second.id)
      .then(setDiff)
      .catch((reason) => toast(apiErrorMessage(reason, t("revisions.compareFailed")), "error"));
    // t/toast sind während der Lebensdauer der Komponente unveränderlich
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [compare, revisions, template.id]);

  function toggle(id: string) {
    setCompare((current) => (current.includes(id) ? current.filter((item) => item !== id) : [...current.slice(-1), id]));
  }

  async function restore(revision: RevisionInfo) {
    if (!(await confirm({ message: t("revisions.restoreConfirm", { revision: revision.revision_no }), confirmLabel: t("revisions.restore") }))) return;
    try {
      await studioApi.restoreRevision(template.id, revision.id);
      toast(t("revisions.restored"), "success");
      onRestored();
    } catch (reason) {
      toast(apiErrorMessage(reason, t("common.actionFailed")), "error");
    }
  }

  return (
    <Modal className="studio-modal" open onClose={onClose} title={t("revisions.title", { name: template.name })} description={t("revisions.description")} size="wide">
      {error && <StatusBanner tone="error" message={error} />}
      {!revisions && !error && <p className="muted">{t("common.loading")}</p>}
      {revisions && (
        <div className="table-shell">
          <table className="data-table">
            <thead>
              <tr>
                <th scope="col">{t("revisions.compare")}</th>
                <th scope="col">{t("revisions.revision")}</th>
                <th scope="col">{t("revisions.status")}</th>
                <th scope="col">{t("revisions.changed")}</th>
                <th scope="col">{t("revisions.note")}</th>
                <th scope="col" aria-label={t("revisions.actions")} />
              </tr>
            </thead>
            <tbody>
              {revisions.map((revision) => (
                <tr key={revision.id}>
                  <td>
                    <input type="checkbox" checked={compare.includes(revision.id)} onChange={() => toggle(revision.id)} aria-label={t("revisions.compareSelect", { revision: revision.revision_no })} />
                  </td>
                  <td>{t("revisions.number", { revision: revision.revision_no })}</td>
                  <td>
                    <Badge variant={STATUS_VARIANT[revision.status]}>{t(`revisions.statusLabel.${revision.status}`)}</Badge>
                  </td>
                  <td>
                    {formatDateTime(revision.published_at ?? revision.updated_at, locale)}
                    {revision.created_by_name ? ` · ${revision.created_by_name}` : ""}
                  </td>
                  <td>{revision.note ?? ""}</td>
                  <td>
                    {revision.status !== "draft" && template.editable && (
                      <button type="button" className="button-secondary" onClick={() => void restore(revision)}>
                        {t("revisions.restore")}
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {compare.length < 2 && <p className="field-help">{t("revisions.compareHint")}</p>}
      {diff && (
        <section className="studio-diff" aria-label={t("revisions.differences")}>
          <h3 className="studio-section-title">{t("revisions.differences")}</h3>
          {diff.nodes.length === 0 && diff.settings.length === 0 && diff.masters.length === 0 && <p className="muted">{t("revisions.noDifferences")}</p>}
          <ul className="studio-diff-list">
            {diff.settings.map((key) => (
              <li key={`s-${key}`}>
                <Badge variant="info">{t("revisions.change.modified")}</Badge> {t(`revisions.settingsArea.${key}`)}
              </li>
            ))}
            {diff.masters.map((key) => (
              <li key={`m-${key}`}>
                <Badge variant="info">{t("revisions.change.modified")}</Badge> {t("revisions.master", { name: key })}
              </li>
            ))}
            {diff.nodes.map((change, index) => (
              <li key={`${change.node_id}-${change.change}-${index}`}>
                <Badge variant={change.change === "added" ? "success" : change.change === "removed" ? "danger" : "info"}>{t(`revisions.change.${change.change}`)}</Badge>{" "}
                {change.name || t(`nodeType.${change.type}`)}
                {change.fields?.length ? <span className="muted"> · {change.fields.map((field) => t(`revisions.field.${field}`)).join(", ")}</span> : null}
              </li>
            ))}
          </ul>
        </section>
      )}
    </Modal>
  );
}
