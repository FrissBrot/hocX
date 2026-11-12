"use client";

import { useTranslations } from "next-intl";

import { CopyField } from "@/components/ui/copy-field";
import { Modal } from "@/components/ui/modal";
import { SubmissionAssignment, SubmissionLink } from "@/types/api";

/** Öffentliche Adresse einer Abgabe über ihren bevorzugten Link (Standard vor dem ersten),
 * wie submission_link_service.preferred_link im Backend. */
export function assignmentPublicUrl(assignment: Pick<SubmissionAssignment, "link_ids" | "public_slug">, links: SubmissionLink[]): string | null {
  const own = links.filter((link) => assignment.link_ids.includes(link.id));
  const link = own.find((item) => item.is_default) ?? own[0];
  return link ? `${link.url.replace(/\/+$/, "")}/${assignment.public_slug}` : null;
}

/** Kopierbarer Link der Abgabe oder ein Hinweis, dass sie noch über keinen Link erreichbar ist. */
export function AssignmentLinkField({ assignment, links }: { assignment: SubmissionAssignment; links: SubmissionLink[] }) {
  const t = useTranslations("submissionAssignments");
  const url = assignmentPublicUrl(assignment, links);
  return url ? (
    <div className="subm-link-field">
      <CopyField label={t("publicLinkLabel")} value={url} />
    </div>
  ) : (
    <p className="field-help">{t("createdNoLink")}</p>
  );
}

/** Nach dem Anlegen: Link zum Teilen gleich zur Hand, statt nur einer kurzen Meldung. */
export function SubmissionCreatedModal({
  assignment,
  links,
  onClose,
}: {
  assignment: SubmissionAssignment | null;
  links: SubmissionLink[];
  onClose: () => void;
}) {
  const t = useTranslations("submissionAssignments");
  const url = assignment ? assignmentPublicUrl(assignment, links) : null;
  return (
    <Modal open={assignment !== null} onClose={onClose} title={t("createdTitle")} description={assignment?.title}>
      {assignment ? (
        <div className="grid subm-created">
          <span className="subm-created-check" aria-hidden="true">✓</span>
          <p>{url ? t("createdIntro") : t("createdNoLink")}</p>
          {url ? (
            <div className="subm-link-field">
              <CopyField label={t("publicLinkLabel")} value={url} />
            </div>
          ) : null}
          <div className="modal-actions">
            {url ? (
              <a className="button-secondary" href={url} target="_blank" rel="noopener noreferrer">
                {t("openBox")}
              </a>
            ) : null}
            <button type="button" className="button-primary" onClick={onClose}>
              {t("done")}
            </button>
          </div>
        </div>
      ) : null}
    </Modal>
  );
}
